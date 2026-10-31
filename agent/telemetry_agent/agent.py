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

MAX_CALLS_PER_REPLY = 5
MAX_TOOL_ARGUMENT_CHARS = 20000
MAX_TOOL_CONTENT_CHARS = 32000


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
                return self._finish(_message_text(msg), trace)
            self._run_calls(calls, trace, routed_by="llm", content=_message_text(msg, default=""))

        # Out of tool rounds: force a plain-text answer from what we have.
        self.messages.append({"role": "user", "content": "Stop calling tools. Summarize what you found and give the learner the single next step."})
        msg = self.llm.chat(self.messages)
        return self._finish(_message_text(msg), trace)

    def _run_calls(self, calls: list[dict], trace: list[dict], routed_by: str, content: str = ""):
        content = content[:MAX_TOOL_CONTENT_CHARS]
        self.messages.append({"role": "assistant", "content": content,
                              "tool_calls": [{"id": c["id"], "type": "function",
                                              "function": {"name": c["name"], "arguments": json.dumps(c["args"] if c.get("validation_error") is None else {})}}
                                             for c in calls]})
        for c in calls:
            if c.get("validation_error") is not None:
                result = {"error": c["validation_error"], "executed": False}
            elif c["name"] not in self.tool_names:
                result = {"error": {"code": "unknown_tool", "message": "Only the documented tools may be called."}, "executed": False}
            else:
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
            rewrite = _message_text(self.llm.chat(self.messages)).strip()
            self.messages = self.messages[:-2]  # don't keep the failed draft in the conversation
            still = guardrails.check(rewrite)
            reply.text = guardrails.scrub(rewrite, still) if still else rewrite
        self.messages.append({"role": "assistant", "content": reply.text})
        return reply


_INLINE = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>|```(?:json)?\s*(.*?)\s*```", re.S)


def _message_text(message, default="The local model did not return usable response text. Please try again.") -> str:
    if isinstance(message, dict) and isinstance(message.get("content"), str):
        return message["content"]
    return default


def _rejected(code: str, message: str, name="invalid_tool_call") -> dict:
    """No raw malformed arguments are copied into traces or fed back to the model."""
    return {"id": _id(), "name": name, "args": None,
            "validation_error": {"code": code, "message": message}}


def _strict_json(text: str):
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result

    def reject_constant(value):
        raise ValueError("non-finite JSON")
    return json.loads(text, object_pairs_hook=unique_pairs, parse_constant=reject_constant)


def _parsed_call(name, args, known, *, arguments_present=True):
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", name):
        return _rejected("invalid_tool_name", "A tool name must be a documented identifier.")
    if name not in known:
        return _rejected("unknown_tool", "Only the documented tools may be called.", name)
    if not arguments_present:
        return _rejected("missing_arguments", "Supply an explicit JSON argument object, including {} for a tool with no arguments.", name)
    if isinstance(args, str):
        if len(args) > MAX_TOOL_ARGUMENT_CHARS:
            return _rejected("arguments_too_large", "Tool arguments exceed the size limit.", name)
        try:
            args = _strict_json(args)
        except (ValueError, TypeError, RecursionError):
            return _rejected("invalid_argument_json", "Tool arguments must be valid JSON with unique keys and finite numbers.", name)
    if not isinstance(args, dict):
        return _rejected("arguments_not_object", "Tool arguments must be a JSON object; the call was not executed.", name)
    try:
        encoded = json.dumps(args, allow_nan=False, ensure_ascii=False)
        if len(encoded) > MAX_TOOL_ARGUMENT_CHARS:
            return _rejected("arguments_too_large", "Tool arguments exceed the size limit.", name)
        # Even a Python-supplied dict must have proper JSON string keys and values.
        if any(not isinstance(key, str) for key in args):
            raise ValueError("non-string key")
        _strict_json(encoded)
    except (ValueError, TypeError, RecursionError):
        return _rejected("invalid_argument_json", "Tool arguments must contain only valid JSON values.", name)
    return {"id": _id(), "name": name, "args": args}


def _tool_calls(msg: dict, known: set[str]) -> list[dict]:
    """Parse bounded native/inline calls; rejected calls produce errors, never defaults.

    A malformed call is returned as a non-executable error so the model can correct
    it. More than five calls rejects the entire reply instead of running a prefix.
    """
    if not isinstance(msg, dict):
        return [_rejected("invalid_message", "The local model response must be an object.")]
    native = msg.get("tool_calls")
    if native is not None and not isinstance(native, list):
        return [_rejected("invalid_call_list", "tool_calls must be a JSON array.")]
    if native:
        if len(native) > MAX_CALLS_PER_REPLY:
            return [_rejected("too_many_tool_calls", "At most five tool calls are allowed per reply; no calls from this reply were executed.")]
        calls = []
        for call in native:
            if not isinstance(call, dict) or call.get("type", "function") != "function" or not isinstance(call.get("function"), dict):
                calls.append(_rejected("invalid_call", "Each tool call must contain a function object."))
                continue
            fn = call["function"]
            calls.append(_parsed_call(fn.get("name"), fn.get("arguments"), known,
                                      arguments_present="arguments" in fn))
        return calls
    content = msg.get("content")
    if content is None:
        return []
    if not isinstance(content, str):
        return [_rejected("invalid_content", "The local model response content must be text.")]
    if len(content) > MAX_TOOL_CONTENT_CHARS:
        return [_rejected("content_too_large", "The local model response exceeded the tool-parsing limit.")]
    if content.count("<tool_call>") != content.count("</tool_call>"):
        return [_rejected("incomplete_inline_call", "Inline tool-call tags must be complete; no calls from this reply were executed.")]
    candidates = [(match.group(1) if match.group(1) is not None else match.group(2),
                   match.group(1) is not None) for match in _INLINE.finditer(content)]
    if not candidates and content.strip().startswith("{"):
        candidates = [(content.strip(), False)]
    if len(candidates) > MAX_CALLS_PER_REPLY:
        return [_rejected("too_many_tool_calls", "At most five tool calls are allowed per reply; no calls from this reply were executed.")]
    calls = []
    for payload, explicit in candidates:
        try:
            obj = _strict_json(payload)
        except (ValueError, TypeError, RecursionError):
            if explicit or re.search(r'"(?:name|tool)"\s*:', payload):
                calls.append(_rejected("invalid_call_json", "Inline tool calls must be valid JSON objects."))
            continue
        if not isinstance(obj, dict):
            if explicit:
                calls.append(_rejected("call_not_object", "An inline tool call must be a JSON object."))
            continue
        if not explicit and "name" not in obj and "tool" not in obj:
            continue  # ordinary JSON examples are not execution requests
        if "name" in obj and "tool" in obj:
            calls.append(_rejected("ambiguous_tool_name", "Use either name or tool, never both."))
            continue
        name = obj.get("name") if "name" in obj else obj.get("tool")
        if "arguments" in obj and "parameters" in obj:
            calls.append(_rejected("ambiguous_arguments", "Use either arguments or parameters, never both."))
            continue
        field = "arguments" if "arguments" in obj else "parameters"
        calls.append(_parsed_call(name, obj.get(field), known, arguments_present=field in obj))
    return calls


def _id() -> str:
    return "call_" + uuid.uuid4().hex[:8]
