"""Loopback-only lab helper: manual installation, bounded tools, local JSON export.

Run from the agent folder: python -m telemetry_agent.helper
A random launch token stays in the URL fragment and is required on every API call.
The helper never installs software, starts a runtime, downloads a model, executes
a browser/model-selected shell command, or disables an OS security control.
"""
from __future__ import annotations

import argparse
import copy
import dataclasses
import hashlib
import json
import math
import platform
import re
import secrets
import shutil
import statistics
import threading
import time
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from . import guardrails
from .agent import LabAgent
from .config import Settings
from .llm import ChatClient, LLMError
from .tools import Toolbox, _brief, validate_tool_args

WEB_DIR = Path(__file__).resolve().parent / "web"
CONTENT_TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
                 ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml"}
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
       "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
MAX_BODY, MAX_EXPORT_BYTES = 64 * 1024, 10 * 1024**2
OLLAMA_DOWNLOAD = "https://ollama.com/download"
GOALS = {
    "try": {"label": "Try a small model", "detail": "Start with a smaller candidate.", "prefer": "faster_option",
            "why": "A smaller parameter count is a planning choice; measure actual speed and output quality."},
    "study": {"label": "Explore concepts", "detail": "Explain and test local inference.", "prefer": "recommended",
              "why": "Choose using current resources, then evaluate the model's answers critically."},
    "write": {"label": "Explore writing", "detail": "Compare sample outputs.", "prefer": "recommended",
              "why": "These are resource-based candidates, not verified writing-quality rankings."},
    "code": {"label": "Explore coding", "detail": "Inspect and verify sample explanations.", "prefer": "stronger_option",
             "why": "A larger candidate may fit; coding quality still requires evaluation."},
}
ACTIONS = {
    "check_hardware": set(),
    "check_install": {"up_to_step"},
    "first_prompt": {"model"},
    "benchmark": {"model", "repeats", "guess_tps", "guess_ram_gb"},
}


class BadRequest(ValueError):
    pass


class Busy(RuntimeError):
    pass


def _text(value, name, limit=6000, allow_empty=False):
    if not isinstance(value, str) or len(value) > limit or (not allow_empty and not value.strip()):
        raise BadRequest(f"{name} must be text within the stated length limit.")
    return value.strip()


def _safe_text(value):
    text = guardrails.redact_secrets(str(value))
    text = re.sub(r"(?:/Users/|/home/|[A-Za-z]:[\\/])[^\s\"'<>]+", "[local path omitted]", text)
    return text[:6000]


def pick_for_goal(rec: dict, goal: str) -> dict | None:
    return rec.get(GOALS.get(goal, GOALS["study"])["prefer"]) or rec.get("recommended")


class Lab:
    """One learner, one manual lab; inference and jobs are serialized."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or Settings()
        self.tools = Toolbox(self.settings)
        self.allowed = {m["ollama_tag"]: m for m in self.tools.allow_list}
        self.jobs = {}
        self._agents = {}
        self._jobs_lock = threading.RLock()
        self._operation_lock = threading.Lock()
        self._chat_lock = threading.Lock()

    def status(self):
        runtime = self.runtime_state()
        model = self._agent_model(runtime["lab_models"])
        return {"runtime": runtime, "installation_mode": "manual",
                "assistant": {"ready": bool(model), "model": model, "wanted_model": self.settings.agent_model,
                              "guardrails_required": True, "comparison_mode": "Use the isolated text-only evaluation harness."},
                "platform_validation": "Windows implementation has automated tests, but no physical Windows validation is claimed.",
                "goals": {k: {"label": g["label"], "detail": g["detail"]} for k, g in GOALS.items()}}

    def runtime_state(self):
        try:
            models = ChatClient(self.settings.base_url, self.settings.agent_model).list_models()
            running = True
        except LLMError:
            models, running = [], False
        binary = "ollama" if self.settings.runtime == "ollama" else "llama-server"
        installed = running or bool(shutil.which(binary))
        if self.settings.runtime == "ollama" and platform.system() == "Darwin":
            installed = installed or any(p.is_dir() for p in (Path("/Applications/Ollama.app"), Path.home() / "Applications/Ollama.app"))
        return {"name": "Ollama" if self.settings.runtime == "ollama" else "llama.cpp (experimental)",
                "installed": bool(installed), "running": running, "models": models,
                "lab_models": [m for m in models if m in self.allowed], "download_url": OLLAMA_DOWNLOAD,
                "models_folder": "Runtime-managed local model storage; verify its actual location with your runtime.",
                "manual_only": True}

    def recommend(self, goal):
        if not isinstance(goal, str) or goal not in GOALS:
            raise BadRequest("Choose one of the listed goals.")
        rec = self.tools.recommend_model()
        options = sorted((o for o in (rec.get("recommended"), rec.get("faster_option"), rec.get("stronger_option")) if o),
                         key=lambda o: o["params_billion"])
        return {**rec, "goal": goal, "goal_why": GOALS[goal]["why"], "pick": pick_for_goal(rec, goal), "options": options}

    def plan(self, model):
        m = self._allowed_model(model)
        rt = self.runtime_state()
        system = platform.system()
        if self.settings.runtime != "ollama":
            return {"model": _brief(m), "installation_mode": "manual", "steps": [],
                    "supported_stop": "This build has not verified a llama.cpp model-provenance path. Use the supported Ollama lab or ask the team."}
        start = "Open the Ollama application from your user account." if system in {"Windows", "Darwin"} else "ollama serve"
        cli = "ollama"
        if system == "Darwin" and not shutil.which("ollama"):
            if (Path.home() / "Applications/Ollama.app/Contents/Resources/ollama").is_file():
                cli = '"$HOME/Applications/Ollama.app/Contents/Resources/ollama"'
            elif Path("/Applications/Ollama.app/Contents/Resources/ollama").is_file():
                cli = '"/Applications/Ollama.app/Contents/Resources/ollama"'
        instructions = ("Review the official installer for your OS. Use a standard-user installation only. "
                        "If the installer asks for admin access, or the OS blocks it, stop and ask the team for a supported route. "
                        "Do not disable Gatekeeper, antivirus, execution policy, or other security protections.")
        steps = [
            _step("install_runtime", "Manually install the runtime", done=rt["installed"], kind="manual",
                  link=OLLAMA_DOWNLOAD, why="Model weights need a runtime that loads them and performs inference.",
                  does=instructions),
            _step("start_runtime", "Manually start your runtime", done=rt["running"], kind="manual", command=start,
                  why="The lab talks to a model server on this laptop only.",
                  does="Open/start it yourself. This helper does not launch programs or change system settings."),
            _step("pull_model", f"Manually download {model}", done=model in rt["models"], kind="manual",
                  command=f"{cli} pull {model}", why="Download the exact catalog tag, then verify the result.",
                  does=f"The catalog estimates about {m['size_gb']} GiB; the actual artifact and quantization must be checked. Count the whole lab/runtime and any other models toward the total budget."),
            _step("verify_install", "Verify the manual steps", done=False, action="check_install", args={"up_to_step": 4},
                  why="Check observable prerequisites without hiding the installation process.",
                  does="Read runtime/model state, provenance and total disk budget. This does not install or download anything."),
            _step("first_prompt", "Run a bounded first prompt", done=False, args={"model": model},
                  why="A real response verifies that the prepared model can perform inference.",
                  does="After resource checks, ask the selected model for a short greeting. Timing depends on this device."),
        ]
        return {"model": _brief(m), "installation_mode": "manual", "steps": steps}

    def start_job(self, action, args=None):
        if not isinstance(action, str) or action not in ACTIONS:
            raise BadRequest("Unknown or unsupported action. Installation, downloads and runtime launch are manual.")
        if args is None:
            args = {}
        if not isinstance(args, dict) or set(args) - ACTIONS[action]:
            raise BadRequest("Arguments must be an object containing only the action's documented keys.")
        args = dict(args)
        if "model" in ACTIONS[action]:
            self._allowed_model(args.get("model"))
        try:
            if action == "check_install":
                validate_tool_args("check_install", args)
            elif action == "benchmark":
                validate_tool_args("run_benchmark", args)
            elif action == "first_prompt":
                validate_tool_args("run_benchmark", {"model": args["model"]})
        except ValueError as exc:
            raise BadRequest(str(exc)) from exc
        with self._jobs_lock:
            for job in self.jobs.values():
                if job["status"] == "running" and job["action"] == action and job["args"] == args:
                    return copy.deepcopy(job)
            if not self._operation_lock.acquire(blocking=False):
                raise Busy("Another lab operation is running. Wait before starting a new one.")
            job = {"id": uuid.uuid4().hex[:12], "action": action, "args": args, "status": "running",
                   "progress": None, "detail": "", "log": [], "result": None, "error": None, "diagnosis": None,
                   "warning": None}
            # Keep bounded history; never discard a running job.
            if len(self.jobs) >= 100:
                oldest = next((key for key, value in self.jobs.items() if value["status"] != "running"), None)
                if oldest:
                    del self.jobs[oldest]
            self.jobs[job["id"]] = job
            threading.Thread(target=self._run_job, args=(job,), daemon=True).start()
            return copy.deepcopy(job)

    def job(self, job_id):
        with self._jobs_lock:
            if not re.fullmatch(r"[a-f0-9]{12}", job_id) or job_id not in self.jobs:
                raise LookupError("Job not found.")
            return copy.deepcopy(self.jobs[job_id])

    def _run_job(self, job):
        try:
            result = getattr(self, "_do_" + job["action"])(job, **job["args"])
            with self._jobs_lock:
                job["result"], job["status"] = result, "done"
                if job["action"] == "benchmark":
                    total, failed, partial = result.get("runs", 0), result.get("failed_runs", 0), result.get("partial_runs", 0)
                    if total > 0 and failed >= total:
                        job.update(status="failed", error="All benchmark requests failed. Error records were saved locally; inspect Results and check the manual setup before retrying.")
                    elif failed or partial:
                        job.update(status="partial", warning=f"Recorded with limitations: {failed} failed and {partial} partial runs. This is not complete acceptance evidence.")
        except Exception as exc:
            error = _safe_text(exc)
            diagnosis = self.tools.read_logs(error or "Unknown operation failure")["matches"]
            with self._jobs_lock:
                job.update(error=error, diagnosis=diagnosis[0] if diagnosis else None, status="failed")
        finally:
            self._operation_lock.release()

    def _do_check_hardware(self, job):
        job["log"].append("Reading this laptop's hardware and account privilege level.")
        return self.tools.check_hardware()

    def _do_check_install(self, job, up_to_step=4):
        result = self.tools.check_install(up_to_step)
        if result["steps"] and not result["steps"][-1]["ok"]:
            raise RuntimeError(result["steps"][-1]["detail"] + " " + result["steps"][-1].get("fix", ""))
        return result

    def _do_first_prompt(self, job, model):
        self.tools.ensure_model_ready(model)
        job["log"].append("Running a bounded first prompt after provenance and total-budget checks.")
        start = time.perf_counter()
        reply = ChatClient(self.settings.base_url, model, timeout=120).chat(
            [{"role": "user", "content": "Say hello in three words."}], max_tokens=12)
        text = (reply.get("content") or "").strip()
        if not text:
            raise RuntimeError("The local model returned no text.")
        return {"reply": _safe_text(text), "seconds": round(time.perf_counter() - start, 2)}

    def _do_benchmark(self, job, model, repeats=3, guess_tps=None, guess_ram_gb=None):
        job["log"].append("Warm-up, then three fixed prompts and three measured repetitions per prompt by default.")
        result = self.tools.run_benchmark(model, repeats=repeats, guess_tps=guess_tps, guess_ram_gb=guess_ram_gb)
        if result.get("error"):
            raise RuntimeError(result["error"])
        if result.get("saved_to"):
            result["saved_to"] = Path(result["saved_to"]).name
        job["log"].append("Session saved locally; download the anonymous JSON in Results.")
        return result

    def chat(self, text, guardrails_on=True):
        text = _text(text, "message")
        if type(guardrails_on) is not bool or not guardrails_on:
            raise BadRequest("Live helper safety stays on. Use the isolated evaluation harness for the text-only comparison.")
        model = self._agent_model(self.runtime_state()["lab_models"])
        if not model:
            # Rule-based bootstrap: no nonexistent model or hidden cloud dependency.
            return {"text": self._bootstrap_text(text),
                    "model": None, "guardrails": True, "guardrail_intervened": False, "flagged": [],
                    "trace": [], "mode": "static_bootstrap"}
        if not self._operation_lock.acquire(blocking=False):
            raise Busy("A lab operation is running. Wait so tutoring does not contaminate the benchmark.")
        try:
            self.tools.ensure_model_ready(model)
            with self._chat_lock:
                if model not in self._agents:
                    self._agents[model] = LabAgent(dataclasses.replace(self.settings, guardrails=True, agent_model=model))
                agent = self._agents[model]
                if len(agent.messages) > 80:
                    agent.reset()
                reply = agent.ask(guardrails.redact_secrets(text))
            return {"text": _safe_text(reply.text), "model": model, "guardrails": True,
                    "guardrail_intervened": reply.guardrail_intervened,
                    "flagged": sorted({v.rule for v in reply.raw_violations}),
                    "trace": [{"tool": s["tool"], "args": _safe_text(json.dumps(s["args"])),
                               "chosen_by": s["chosen_by"], "result": _safe_text(json.dumps(s["result"], default=str))[:1500]}
                              for s in reply.trace], "mode": "local_model"}
        finally:
            self._operation_lock.release()

    def reset_chat(self):
        if not self._operation_lock.acquire(blocking=False):
            raise Busy("Wait for the running operation before resetting the conversation.")
        try:
            with self._chat_lock:
                self._agents.clear()
            return {"ok": True}
        finally:
            self._operation_lock.release()

    def diagnose(self, text):
        return self.tools.read_logs(_text(text, "text", 16000))

    def _bootstrap_text(self, text):
        """Static concepts/catalog help before the local tutoring model exists."""
        diagnosis = self.tools.read_logs(text)
        if diagnosis["matches"]:
            match = diagnosis["matches"][0]
            return match["title"] + ": " + match["cause"] + "\n" + "\n".join(match["fix"])
        lower = text.lower()
        if "token" in lower or "tps" in lower or "throughput" in lower:
            return "Tokens are text pieces chosen by the model's tokenizer. Decode TPS is generated tokens divided by runtime-reported generation seconds. The lab's first-text latency is a client-observed proxy, since a streamed text chunk can contain more than one token. Follow Deploy to prepare a real model before measuring."
        if "ram" in lower or "memory" in lower:
            return "Model weights, runtime state and conversation/context use memory. Available RAM right now matters; total installed RAM is not the amount free for a new model. Check your hardware and the provisional model estimates in Deploy."
        if "local" in lower or "cloud" in lower or "runtime" in lower:
            return "A language model is a set of learned weights. A runtime loads those weights and performs inference. Local inference runs on your laptop; cloud inference runs on a remote service. This lab uses a loopback-only local runtime and does not send your questions to a cloud model."
        if "quant" in lower:
            return "Quantization represents model weights using fewer bits to reduce storage and memory. Its quality and speed effects depend on the exact model, artifact and device. A catalog GGUF format does not prove the quantization of an Ollama tag."
        return "No local tutoring model is ready yet. Follow the manual Deploy instructions, use 'Check installation' to verify completed steps, or paste a short redacted error for catalog-based help. This answer is static guidance, not generated by an LLM."

    def try_model(self, model, message):
        self._allowed_model(model)
        message = guardrails.redact_secrets(_text(message, "message", 2000))
        if not self._operation_lock.acquire(blocking=False):
            raise Busy("Wait for the current lab operation before generating text.")
        try:
            self.tools.ensure_model_ready(model)
            start, first, parts, tokens, duration = time.perf_counter(), None, [], None, None
            for ts, delta, usage in ChatClient(self.settings.base_url, model, timeout=120).benchmark_stream(
                    [{"role": "user", "content": message}], runtime=self.settings.runtime,
                    max_tokens=128, temperature=0, context_tokens=2048):
                if delta:
                    first = ts if first is None else first
                    parts.append(delta)
                if usage and type(usage.get("completion_tokens")) is int:
                    tokens = usage["completion_tokens"]
                if usage and usage.get("source") == "ollama_native":
                    count, nanos = usage.get("eval_count"), usage.get("eval_duration")
                    if type(count) is int and 0 <= count <= 128:
                        tokens = count
                    if type(nanos) in (int, float) and math.isfinite(nanos) and nanos > 0:
                        duration = nanos / 1e9
            output = _safe_text("".join(parts).strip())
            violations = guardrails.check(output)
            if violations:
                output = guardrails.scrub(output, violations)
            tps = round(tokens / duration, 3) if tokens is not None and 0 <= tokens <= 128 and duration else None
            return {"text": output, "output_filtered": bool(violations),
                    "ttft_s": round(first - start, 3) if first is not None else None,
                    "ttft_method": "client-observed first nonempty text chunk; not exact first-token instrumentation",
                    "tps": tps, "tps_unavailable_reason": None if tps is not None else "Native generation duration or bounded token count is unavailable.",
                    "tokens": tokens}
        finally:
            self._operation_lock.release()

    def _exports(self):
        from . import protocol
        folder = self.settings.results_dir.resolve()
        docs = []
        if not folder.is_dir():
            return docs
        paths = sorted(folder.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:100]
        for path in paths:
            try:
                if path.is_symlink() or path.resolve().parent != folder or path.stat().st_size > MAX_EXPORT_BYTES:
                    continue
                doc = protocol.load_session(path)
                docs.append(doc)
            except (OSError, ValueError, TypeError):
                continue
        return docs

    def results_json(self):
        from . import protocol
        docs = self._exports()
        if not docs:
            raise LookupError("No valid schema-v1 benchmark session yet.")
        # Validation + explicit sanitization protect against legacy/local artifact extras.
        doc = _anonymous_export(copy.deepcopy(docs[0]))
        # A schema-valid legacy summary is not trustworthy: it may contain free
        # text, private labels, or arbitrary nested fields. Recompute it.
        doc["summary"] = protocol.canonical_summary(doc)
        return protocol.validate_session(doc)

    def results(self):
        from . import protocol
        models = []
        rows = 0
        for doc in self._exports():
            runs = doc.get("runs", [])
            rows += len(runs)
            summary = protocol.summarize_runs(runs)
            models.append({"machine": "This laptop", "model": doc.get("model", {}).get("name", "unknown") if isinstance(doc.get("model"), dict) else "unknown",
                           "runs": len(runs), "median_tps": summary.get("median_tps"),
                           "median_ttft_ms": summary.get("median_ttft_ms"), "peak_ram_mb": summary.get("peak_ram_mb"),
                           "last_run": doc.get("created_at", ""), "session_id": doc.get("session_id"),
                           "valid_runs": summary["valid_runs"], "partial_runs": summary["partial_runs"],
                           "failed_runs": summary["failed_runs"], "data_kind": doc["data_kind"]})
        return {"rows": rows, "models": models, "download": "/api/results.json",
                "download_scope": "Latest valid anonymous schema-v1 session; imported files stay in the portal browser."}

    def _allowed_model(self, model):
        if not isinstance(model, str) or model not in self.allowed:
            raise BadRequest("Choose an exact model from the lab's allow-list, never a path or URL.")
        return self.allowed[model]

    def _agent_model(self, lab_models):
        if self.settings.agent_model in lab_models and self.settings.agent_model in self.allowed:
            return self.settings.agent_model
        return min(lab_models, key=lambda m: self.allowed[m]["params_b"], default=None)


def _anonymous_export(value, key=""):
    """Conservative export scrub; schema validation remains the authority on shape."""
    forbidden = {"tester", "machine_label", "hostname", "username", "user", "path", "saved_to",
                 "raw_log", "raw_logs", "raw_prompt", "prompt_text", "api_key", "token", "password", "secret"}
    if isinstance(value, dict):
        result = {k: _anonymous_export(v, k) for k, v in value.items() if k.lower() not in forbidden and not k.lower().endswith("_path")}
        if key == "":
            result["summary"] = {}
            # Do not preserve user-chosen aliases or identifiers from older files.
            result["session_id"] = hashlib.sha256(("session:" + str(value["session_id"])).encode()).hexdigest()[:32]
            result["device"]["alias"] = "device-" + result["session_id"][:8]
        if key == "runs":
            result["run_id"] = hashlib.sha256(("run:" + str(value["run_id"])).encode()).hexdigest()[:32]
            if result.get("error") is not None:
                result["error"] = "The local request or measurement failed; diagnostic details are retained locally."
        return result
    if isinstance(value, list):
        return [_anonymous_export(v, key) for v in value]
    if isinstance(value, str):
        return _safe_text(value)
    return value


def _step(id, title, *, done, why, does, command=None, kind="action", action=None, args=None, link=None):
    return {"id": id, "action": (action or id) if kind == "action" else None, "kind": kind, "title": title,
            "done": bool(done), "why": why, "does": does, "command": command, "args": args or {}, "link": link}


def _body_fields(body, allowed, required=()):
    if set(body) - set(allowed) or any(k not in body for k in required):
        raise BadRequest("Unexpected or missing request fields.")


def make_handler(lab: Lab, token: str):
    class Handler(BaseHTTPRequestHandler):
        server_version = "LabHelper/1.0"
        sys_version = ""

        def setup(self):
            super().setup()
            self.connection.settimeout(10)

        def log_message(self, fmt, *args):
            pass

        def do_GET(self):
            self._handle("GET")

        def do_POST(self):
            self._handle("POST")

        def do_OPTIONS(self):
            self._json(405, {"error": "Cross-origin access is not supported."})

        def _handle(self, method):
            port = self.server.server_address[1]
            hosts = self.headers.get_all("Host", [])
            allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
            if len(hosts) != 1 or hosts[0] not in allowed_hosts:
                return self._json(403, {"error": "Forbidden host."})
            origins = self.headers.get_all("Origin", [])
            origin = origins[0] if origins else None
            if len(origins) > 1 or (origin is not None and origin != "http://" + hosts[0]):
                return self._json(403, {"error": "Forbidden origin."})
            safe_top_navigation = (method == "GET" and self.path in {"/", "/index.html"}
                                   and self.headers.get("Sec-Fetch-Mode") == "navigate"
                                   and self.headers.get("Sec-Fetch-Dest") == "document")
            if self.headers.get("Sec-Fetch-Site") == "cross-site" and not safe_top_navigation:
                return self._json(403, {"error": "Cross-site requests are disabled."})
            # BaseHTTPRequestHandler normalizes leading //; inspect the original
            # request target so ambiguous paths do not become valid API routes.
            raw = self.requestline.split()[1]
            if not raw.startswith("/") or raw.startswith("//") or any(c in raw for c in ("%", "\\", "?", "#")):
                return self._json(400, {"error": "Invalid request path."})
            path = urlsplit(raw).path
            if not path.startswith("/api/"):
                return self._static(path) if method == "GET" else self._json(405, {"error": "Method not allowed."})
            tokens = self.headers.get_all("X-Lab-Token", [])
            if len(tokens) != 1 or not secrets.compare_digest(tokens[0].encode(), token.encode()):
                return self._json(401, {"error": "Missing or wrong lab token. Reopen the launch link."})
            name = path[5:]
            try:
                if method == "GET" and name == "results.json":
                    data = json.dumps(lab.results_json(), ensure_ascii=True, allow_nan=False).encode()
                    return self._send(200, data, "application/json", download="local-ai-lab-session.json")
                if method == "GET" and name == "results.csv":
                    raise BadRequest("Legacy CSV may include personal labels. Download anonymous results.json instead.")
                body = self._body() if method == "POST" else {}
                return self._json(200, self._route(method, name, body))
            except Busy as exc:
                return self._json(409, {"error": str(exc)})
            except (BadRequest, ValueError) as exc:
                return self._json(400, {"error": _safe_text(exc)})
            except LookupError as exc:
                return self._json(404, {"error": _safe_text(exc)})
            except LLMError:
                return self._json(502, {"error": "Local runtime request failed. Check the runtime and use a redacted log excerpt."})
            except Exception:
                return self._json(500, {"error": "The operation could not be completed. Check the local helper window."})

        def _route(self, method, name, b):
            if method == "GET":
                if name == "status":
                    return lab.status()
                if name == "results":
                    return lab.results()
                if name.startswith("jobs/"):
                    return lab.job(name[5:])
            else:
                if name == "recommend":
                    _body_fields(b, {"goal"}, {"goal"})
                    return lab.recommend(b["goal"])
                if name == "plan":
                    _body_fields(b, {"model"}, {"model"})
                    return lab.plan(b["model"])
                if name == "jobs":
                    _body_fields(b, {"action", "args"}, {"action"})
                    return lab.start_job(b["action"], b.get("args"))
                if name == "chat":
                    _body_fields(b, {"message", "guardrails"}, {"message"})
                    return lab.chat(b["message"], b.get("guardrails", True))
                if name == "chat/reset":
                    _body_fields(b, set())
                    return lab.reset_chat()
                if name == "diagnose":
                    _body_fields(b, {"text"}, {"text"})
                    return lab.diagnose(b["text"])
                if name == "try":
                    _body_fields(b, {"model", "message"}, {"model", "message"})
                    return lab.try_model(b["model"], b["message"])
            raise LookupError("No such endpoint.")

        def _body(self):
            lengths = self.headers.get_all("Content-Length", [])
            if self.headers.get("Transfer-Encoding") or len(lengths) != 1 or not re.fullmatch(r"\d{1,8}", lengths[0]):
                raise BadRequest("A single bounded Content-Length is required.")
            length = int(lengths[0])
            if length > MAX_BODY:
                raise BadRequest("Request too large.")
            if self.headers.get("Content-Type", "").split(";")[0].strip().lower() != "application/json":
                raise BadRequest("Content-Type must be application/json.")
            try:
                raw = self.rfile.read(length)
                if len(raw) != length:
                    raise BadRequest("Incomplete request body.")
                body = json.loads(raw or b"{}", parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Non-finite JSON is not allowed.")))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise BadRequest("Body must be valid JSON.") from exc
            if not isinstance(body, dict):
                raise BadRequest("Body must be a JSON object.")
            return body

        def _static(self, path):
            allowed = {"/": "index.html", "/index.html": "index.html", "/app.js": "app.js", "/style.css": "style.css"}
            if path not in allowed:
                return self._json(404, {"error": "Not found."})
            file = WEB_DIR / allowed[path]
            return self._send(200, file.read_bytes(), CONTENT_TYPES[file.suffix])

        def _json(self, code, payload):
            self._send(code, json.dumps(payload, default=str, allow_nan=False).encode(), "application/json; charset=utf-8")

        def _send(self, code, data, ctype, download=None):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Security-Policy", CSP)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Cross-Origin-Resource-Policy", "same-origin")
            if download:
                self.send_header("Content-Disposition", f'attachment; filename="{download}"')
            self.end_headers()
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass

    return Handler


def create_server(lab, token, port=8765):
    if type(port) is not int or not 0 <= port <= 65535:
        raise ValueError("Port must be an integer from 0 to 65535.")
    if not isinstance(token, str) or not token:
        raise ValueError("A nonempty per-launch token is required.")
    for p in ([0] if port == 0 else range(port, min(port + 20, 65536))):
        try:
            server = ThreadingHTTPServer(("127.0.0.1", p), make_handler(lab, token))
            server.daemon_threads = True
            return server
        except PermissionError as exc:
            raise RuntimeError("The operating system denied opening the local helper port. Use an allowed local session; do not elevate or disable security controls.") from exc
        except OSError:
            continue
    raise RuntimeError("No free helper port. Close the other helper or select another local port.")


def main(argv=None):
    parser = argparse.ArgumentParser(prog="telemetry_agent.helper")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(argv)
    try:
        token = secrets.token_urlsafe(32)
        server = create_server(Lab(), token, args.port)
    except (ValueError, RuntimeError) as exc:
        parser.exit(2, f"Lab could not start: {exc}\n")
    url = f"http://127.0.0.1:{server.server_address[1]}/#t={token}"
    print("Local AI Lab helper is running on this laptop only, in MANUAL installation mode.", flush=True)
    print("Keep this window open. Installation/downloads are performed by the learner.", flush=True)
    print("Windows has not yet been validated on a physical device.", flush=True)
    print(f"Open this private launch link (do not share its token):\n  {url}\n", flush=True)
    if not args.no_browser:
        threading.Timer(0.5, webbrowser.open, (url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
