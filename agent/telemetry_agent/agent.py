"""The lab assistant agent: an LLM that plans with five deterministic tools.

Loop for each learner message:
  1. (guardrails on) redact secrets from the message
  1b. (router on) run the obvious tool for this kind of request (see router.py)
  2. ask the LLM, offering the 5 tool schemas
  3. if it calls tools: run them, send back the JSON results, repeat (max N rounds)
  4. take the final reply and (guardrails on) check it; ask for one rewrite if it
     breaks a safety rule, and scrub the offending lines if it still does
"""
from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field

from . import guardrails
from .config import SKILL_DIR, Settings
from .llm import ChatClient
from .router import route
from .system import hardware_info
from .tools import Toolbox


@dataclass
class AgentReply:
    text: str
    trace: list[dict] = field(default_factory=list)          # every tool call: name, args, result
    raw_violations: list[guardrails.Violation] = field(default_factory=list)  # before the guardrail fixed them
    guardrail_intervened: bool = False


class LabAgent:
    def __init__(self, settings: Settings | None = None, llm=None, toolbox: Toolbox | None = None):
        self.settings = settings or Settings()
        self.llm = llm or ChatClient(self.settings.base_url, self.settings.agent_model)
        self.tools = toolbox or Toolbox(self.settings)
        self.tool_names = {s["function"]["name"] for s in self.tools.schemas()}
        self.model_names = [m["ollama_tag"] for m in self.tools.allow_list]
        hw = hardware_info(self.settings.models_dir)
        system = (SKILL_DIR / "skill.md").read_text()
        system += (f"\n## This learner\nOS: {hw['os']} {hw['os_version']} ({hw['arch']}), runtime: "
                   f"{self.settings.runtime}. Only give commands for this OS.\n")
        if self.settings.guardrails:
            system += "\n" + guardrails.SYSTEM_RULES
        self.messages: list[dict] = [{"role": "system", "content": system}]

    def reset(self):
        self.messages = self.messages[:1]

    def ask(self, user_text: str) -> AgentReply:
        secret_found = False
        if self.settings.guardrails:
            cleaned = guardrails.redact_secrets(user_text)
            secret_found = cleaned != user_text
            if secret_found:
                cleaned += ("\n\n[Note from the safety layer: the learner pasted a secret (token or password) and it "
                            "was removed. Start your reply by telling them not to share secrets in chat and to "
                            "revoke/change it now. You never need their password; nothing in this lab requires admin.]")
            user_text = cleaned
        self.messages.append({"role": "user", "content": user_text})
        trace: list[dict] = []
        if self.settings.router and not secret_found:  # a pasted secret is handled first, not routed
            known =lambda t: bool(self.tools.read_logs(t)["matches"])  # noqa: E731
            routed = [{"id": _id(), "name": n, "args": a} for n, a in route(user_text, self.model_names, known)]
            if routed:
                self._run_calls(routed, trace, routed_by="router")

        for _ in range(self.settings.max_steps):
            msg = self.llm.chat(self.messages, tools=self.tools.schemas())
            calls = _tool_calls(msg, self.tool_names)
            if not calls:
                return self._finish(msg.get("content") or "", trace)
            self._run_calls(calls, trace, routed_by="llm", content=msg.get("content") or "")

        # Out of tool rounds: force a plain-text answer from what we have.
        self.messages.append({"role": "user", "content": "Stop calling tools. Summarize what you found and give the learner the single next step."})
        msg = self.llm.chat(self.messages)
        return self._finish(msg.get("content") or "", trace)

    def _run_calls(self, calls: list[dict], trace: list[dict], routed_by: str, content: str = ""):
        self.messages.append({"role": "assistant", "content": content,
                              "tool_calls": [{"id": c["id"], "type": "function",
                                              "function": {"name": c["name"], "arguments": json.dumps(c["args"])}}
                                             for c in calls]})
        for c in calls:
            result = self.tools.call(c["name"], c["args"])
            trace.append({"tool": c["name"], "args": c["args"], "result": result, "chosen_by": routed_by})
            body = json.dumps(result, default=str)[: self.settings.tool_result_chars]
            self.messages.append({"role": "tool", "tool_call_id": c["id"], "name": c["name"], "content": body})

    def _finish(self, text: str, trace: list[dict]) -> AgentReply:
        reply = AgentReply(text=text.strip(), trace=trace)
        if not self.settings.guardrails:
            reply.raw_violations = guardrails.check(reply.text)
            self.messages.append({"role": "assistant", "content": reply.text})
            return reply

        violations = guardrails.check(reply.text)
        reply.raw_violations = violations
        if violations:
            reply.guardrail_intervened = True
            reasons = "; ".join(sorted({v.reason for v in violations}))
            self.messages.append({"role": "assistant", "content": reply.text})
            self.messages.append({"role": "user", "content":
                                  f"Your last reply broke the safety rules ({reasons}). Rewrite it without that "
                                  "content, keep the rest, and offer a safe alternative."})
            rewrite = (self.llm.chat(self.messages).get("content") or "").strip()
            self.messages = self.messages[:-2]  # don't keep the failed draft in the conversation
            still = guardrails.check(rewrite)
            reply.text = guardrails.scrub(rewrite, still) if still else rewrite
        self.messages.append({"role": "assistant", "content": reply.text})
        return reply


_INLINE = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>|```(?:json)?\s*(\{.*?\})\s*```|^\s*(\{.*\})\s*$", re.S)


def _tool_calls(msg: dict, known: set[str]) -> list[dict]:
    """Native tool calls, or a JSON tool call written into the text (small models do this)."""
    calls = []
    for tc in msg.get("tool_calls") or []:
        fn = tc.get("function", {})
        args = fn.get("arguments") or {}
        if isinstance(args, str):
            try:
                args = json.loads(args or "{}")
            except json.JSONDecodeError:
                args = {}
        calls.append({"id": tc.get("id") or _id(), "name": fn.get("name"), "args": args})
    if calls:
        return calls
    content = msg.get("content") or ""
    for m in _INLINE.finditer(content):
        try:
            obj = json.loads(next(g for g in m.groups() if g))
        except (json.JSONDecodeError, StopIteration):
            continue
        name = obj.get("name") or obj.get("tool")
        if name in known:
            calls.append({"id": _id(), "name": name, "args": obj.get("arguments") or obj.get("parameters") or {}})
    return calls


def _id() -> str:
    return "call_" + uuid.uuid4().hex[:8]
