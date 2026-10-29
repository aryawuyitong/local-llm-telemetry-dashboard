"""Lab Helper: puts the agent in a web page, so learners never need a terminal.

The learner double-clicks a launcher ("Start Lab Helper"). That starts this small
web server on their own laptop and opens the lab website in their browser. The
page uses the same Toolbox, router, guardrails and LabAgent as the CLI.

How the learner gives permission: the page shows each setup step as a card (why,
what changes on the laptop, and the terminal command it replaces). Nothing runs
until they click Approve.

Safety:
  * listens on 127.0.0.1 only, and rejects requests whose Host header isn't this
    server (blocks DNS-rebinding attacks from other websites)
  * every API call needs the random token made at launch; the launcher puts it in
    the page URL, so other websites can't call the helper
  * the page can only start the fixed actions in ACTIONS, with an allow-listed
    model; nothing runs a command written by the LLM or sent by the browser

    python -m telemetry_agent.helper                 start and open the browser
    python -m telemetry_agent.helper --no-browser --port 8765
"""
from __future__ import annotations

import argparse
import csv
import dataclasses
import json
import os
import platform
import secrets
import shutil
import statistics
import subprocess
import threading
import time
import urllib.error
import urllib.request
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from . import guardrails
from .agent import LabAgent
from .config import Settings
from .llm import ChatClient, LLMError
from .tools import Toolbox, _brief

WEB_DIR = Path(__file__).resolve().parent / "web"
CONTENT_TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
                 ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml"}
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
       "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'")
MAX_BODY = 64 * 1024
OLLAMA_DOWNLOAD = "https://ollama.com/download"

# What the learner wants the model for -> which of recommend_model's options to start from.
GOALS = {
    "try": {"label": "Just try it out", "detail": "See a local model work, quickly.", "prefer": "faster_option",
            "why": "A smaller model downloads faster and answers quicker. You can upgrade later."},
    "study": {"label": "Study help", "detail": "Explain concepts, summarize notes, quiz me.", "prefer": "recommended",
              "why": "A balanced pick: good answers, with memory left over for your other apps."},
    "write": {"label": "Writing", "detail": "Draft emails, rewrite paragraphs.", "prefer": "recommended",
              "why": "A balanced pick: good answers, with memory left over for your other apps."},
    "code": {"label": "Coding help", "detail": "Explain errors, write small functions.", "prefer": "stronger_option",
             "why": "Code answers improve a lot with model size, so we start one size up if it fits."},
}

# The only things the page can make the helper do, and the arguments each one accepts.
ACTIONS = {
    "check_hardware": set(),
    "start_runtime": set(),
    "pull_model": {"model"},
    "first_prompt": {"model"},
    "benchmark": {"model", "guess_tps", "guess_ram_gb"},
}


class BadRequest(ValueError):
    pass


def pick_for_goal(rec: dict, goal: str) -> dict | None:
    """The model to suggest first: the goal's preferred option if one fits, else the recommendation."""
    prefer = GOALS.get(goal, GOALS["study"])["prefer"]
    return rec.get(prefer) or rec.get("recommended")


class Lab:
    """Everything the page can ask for. One instance per helper (one learner)."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or Settings()
        self.tools = Toolbox(self.settings)
        self.allowed = {m["ollama_tag"]: m for m in self.tools.allow_list}
        self.jobs: dict[str, dict] = {}
        self._agents: dict[tuple[bool, str], LabAgent] = {}
        self._chat_lock = threading.Lock()

    # ---------------------------------------------------------------- state
    def status(self) -> dict:
        runtime = self.runtime_state()
        agent_model = self._agent_model(runtime["lab_models"])
        return {"runtime": runtime,
                "assistant": {"ready": bool(agent_model), "model": agent_model,
                              "wanted_model": self.settings.agent_model},
                "goals": {k: {"label": g["label"], "detail": g["detail"]} for k, g in GOALS.items()}}

    def runtime_state(self) -> dict:
        try:
            models, running = ChatClient(self.settings.base_url, self.settings.agent_model).list_models(), True
        except LLMError:
            models, running = [], False
        return {"name": "Ollama", "installed": running or bool(_ollama_app()), "running": running,
                "models": models, "lab_models": [m for m in models if m in self.allowed],
                "download_url": OLLAMA_DOWNLOAD, "models_folder": str(Path.home() / ".ollama" / "models")}

    def recommend(self, goal: str) -> dict:
        if goal not in GOALS:
            raise BadRequest(f"Unknown goal '{goal}'.")
        rec = self.tools.recommend_model()
        options = sorted((o for o in (rec.get("recommended"), rec.get("faster_option"), rec.get("stronger_option")) if o),
                         key=lambda o: o["params_billion"])
        return {**rec, "goal": goal, "goal_why": GOALS[goal]["why"], "pick": pick_for_goal(rec, goal), "options": options}

    def plan(self, model: str) -> dict:
        """The setup steps for this model, each marked done if this laptop already has it."""
        m = self._allowed_model(model)
        rt = self.runtime_state()
        system = platform.system()
        start_cmd = {"Darwin": "open -a Ollama", "Windows": "Start menu > Ollama"}.get(system, "ollama serve")
        install_does = ("Opens the Ollama download page. Open the file you get and drag Ollama into Applications."
                        if system == "Darwin" else
                        "Opens the Ollama download page. Run the installer; it installs for your user only.")
        steps = [
            _step("install_runtime", "Install Ollama, the program that runs models", done=rt["installed"],
                  kind="manual", link=OLLAMA_DOWNLOAD,
                  why="A model file is just numbers. Ollama loads it into memory and runs it.",
                  does=install_does),
            _step("start_runtime", "Start Ollama", done=rt["running"],
                  why="Ollama runs a small server on your laptop (port 11434) that this lab talks to.",
                  does="Opens the Ollama app in the background. On a Mac you'll see a llama icon in the menu bar.",
                  command=start_cmd),
            _step("pull_model", f"Download {model}", done=model in rt["models"], args={"model": model},
                  why=(f"This is the model itself: {m['params_b']} billion numbers, compressed ({m['quant']}) "
                       f"to about {m['size_gb']} GB."),
                  does=(f"Downloads about {m['size_gb']} GB into {rt['models_folder']}. "
                        "You can delete it later from Ollama."),
                  command=f"ollama pull {model}"),
            _step("first_prompt", "Say hello to it", done=False, args={"model": model},
                  why="Loading the model into memory and getting a first answer proves every step worked.",
                  does="Loads the model into RAM and asks it to say hello. The first time takes 5-30 seconds.",
                  command=f'ollama run {model} "Say hello in three words."'),
        ]
        return {"model": _brief(m), "steps": steps}

    # ---------------------------------------------------------------- jobs (approved actions)
    def start_job(self, action: str, args: dict | None) -> dict:
        if action not in ACTIONS:
            raise BadRequest(f"Unknown action '{action}'.")
        args = args or {}
        extra = set(args) - ACTIONS[action]
        if extra:
            raise BadRequest(f"Unexpected arguments for {action}: {', '.join(sorted(extra))}")
        if "model" in ACTIONS[action]:
            self._allowed_model(args.get("model", ""))
        for job in self.jobs.values():  # clicking twice doesn't start a second download
            if job["status"] == "running" and job["action"] == action and job["args"] == args:
                return job
        job = {"id": uuid.uuid4().hex[:12], "action": action, "args": args, "status": "running",
               "progress": None, "detail": "", "log": [], "result": None, "error": None, "diagnosis": None}
        self.jobs[job["id"]] = job
        threading.Thread(target=self._run_job, args=(job,), daemon=True).start()
        return job

    def _run_job(self, job: dict):
        try:
            job["result"] = getattr(self, "_do_" + job["action"])(job, **job["args"])
            job["status"] = "done"
        except Exception as e:  # any failure is shown to the learner with a catalog diagnosis
            job["error"] = str(e)
            matches = self.tools.read_logs(str(e))["matches"]
            job["diagnosis"] = matches[0] if matches else None
            job["status"] = "failed"

    def _do_check_hardware(self, job):
        job["log"].append("Reading system, chip, memory and disk…")
        return self.tools.check_hardware()

    def _do_start_runtime(self, job):
        if self.runtime_state()["running"]:
            job["log"].append("Ollama is already running.")
            return {"running": True}
        app = _ollama_app()
        if not app:
            raise RuntimeError("ollama: command not found. Install Ollama first (the step above).")
        job["log"].append(f"Starting {app}…")
        _launch(app)
        for _ in range(40):
            time.sleep(0.75)
            if self.runtime_state()["running"]:
                job["log"].append("Ollama is running on http://localhost:11434.")
                return {"running": True}
        raise RuntimeError("Could not connect to Ollama: it didn't start within 30 seconds. "
                           "Open the Ollama app yourself, then click Approve again.")

    def _do_pull_model(self, job, model):
        if self.settings.runtime != "ollama":
            raise RuntimeError("The Lab Helper downloads models through Ollama. Set AGENT_RUNTIME=ollama.")
        size = self.allowed[model]["size_gb"]
        free = shutil.disk_usage(Path.home()).free / 1024**3
        if free - size < 2:
            raise RuntimeError(f"No space left on device: {model} needs about {size} GB and only {free:.1f} GB "
                               "is free (we keep 2 GB for your system).")
        req = urllib.request.Request(self._native("/api/pull"), headers={"Content-Type": "application/json"},
                                     data=json.dumps({"model": model, "stream": True}).encode())
        last = None
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                for raw in resp:
                    msg = json.loads(raw or b"{}")
                    if msg.get("error"):
                        raise RuntimeError(msg["error"])
                    status = msg.get("status", "")
                    if msg.get("total"):
                        done = msg.get("completed", 0)
                        job["progress"] = round(done / msg["total"], 3)
                        job["detail"] = f"{done / 1024**3:.2f} of {msg['total'] / 1024**3:.2f} GB"
                    label = "Downloading model files…" if status.startswith("pulling ") and status != "pulling manifest" else status
                    if label and label != last:
                        job["log"].append(label)
                        last = label
        except urllib.error.URLError as e:
            raise RuntimeError(f"Could not connect to Ollama at {self._native('')} ({e.reason}).") from e
        if last != "success":
            raise RuntimeError("The download stopped before it finished. Click Approve to resume it.")
        return {"model": model, "downloaded": True}

    def _do_first_prompt(self, job, model):
        job["log"].append(f"Loading {model} into memory…")
        t = time.perf_counter()
        reply = ChatClient(self.settings.base_url, model, timeout=300).chat(
            [{"role": "user", "content": "Say hello in three words."}], max_tokens=12)
        seconds = round(time.perf_counter() - t, 1)
        text = (reply.get("content") or "").strip()
        if not text:
            raise RuntimeError("The model loaded but returned no text. Restart Ollama and try again.")
        job["log"].append(f"{model} replied in {seconds} s: {text}")
        return {"reply": text, "seconds": seconds}

    def _do_benchmark(self, job, model, guess_tps=None, guess_ram_gb=None):
        job["log"].append("Warm-up, then 3 prompts (short, medium, long)…")
        result = self.tools.run_benchmark(model, repeats=1, guess_tps=_num(guess_tps), guess_ram_gb=_num(guess_ram_gb))
        if result.get("error"):
            raise RuntimeError(result["error"])
        job["log"].append(f"Saved on this laptop: {Path(result['saved_to']).name}")
        return result

    # ---------------------------------------------------------------- assistant
    def chat(self, text: str, guardrails_on: bool = True) -> dict:
        text = (text or "").strip()
        if not text:
            raise BadRequest("Empty message.")
        model = self._agent_model(self.runtime_state()["lab_models"])
        if not model:
            raise BadRequest("The assistant needs a downloaded model to think with. Finish the Deploy steps first.")
        with self._chat_lock:  # one conversation per helper; the LLM answers one question at a time
            key = (guardrails_on, model)
            if key not in self._agents:
                self._agents[key] = LabAgent(dataclasses.replace(self.settings, guardrails=guardrails_on, agent_model=model))
            reply = self._agents[key].ask(text)
        return {"text": reply.text, "model": model, "guardrails": guardrails_on,
                "guardrail_intervened": reply.guardrail_intervened,
                "flagged": sorted({v.rule for v in reply.raw_violations}),
                "trace": [{"tool": s["tool"], "args": s["args"], "chosen_by": s["chosen_by"],
                           "result": json.dumps(s["result"], default=str)[:1500]} for s in reply.trace]}

    def reset_chat(self) -> dict:
        with self._chat_lock:
            self._agents.clear()
        return {"ok": True}

    def diagnose(self, text: str) -> dict:
        return self.tools.read_logs(text)

    def try_model(self, model: str, message: str) -> dict:
        """Plain chat with the learner's model (no tools), timed like the collector does."""
        self._allowed_model(model)
        message = guardrails.redact_secrets((message or "").strip())[:2000]
        if not message:
            raise BadRequest("Type a message first.")
        start, first, last, parts, tokens = time.perf_counter(), None, None, [], None
        for ts, delta, usage in ChatClient(self.settings.base_url, model, timeout=300).stream(
                [{"role": "user", "content": message}], max_tokens=300, temperature=0.7):
            if delta:
                first = first or ts
                last = ts
                parts.append(delta)
            if usage:
                tokens = usage.get("completion_tokens")
        tps = round((tokens - 1) / (last - first), 1) if tokens and tokens > 1 and first and last > first else None
        return {"text": "".join(parts).strip(), "ttft_s": round(first - start, 2) if first else None,
                "tps": tps, "tokens": tokens}

    # ---------------------------------------------------------------- results
    def results(self) -> dict:
        path = self.settings.results_dir / "runs.csv"
        if not path.exists():
            return {"rows": 0, "models": []}
        with path.open() as f:
            rows = list(csv.DictReader(f))
        groups: dict[tuple[str, str], list[dict]] = {}
        for r in rows:
            groups.setdefault((r["machine_label"], r["model_name"]), []).append(r)
        models = [{"machine": machine, "model": model, "runs": len(rs),
                   "median_tps": _median(rs, "tps"), "median_ttft_ms": _median(rs, "ttft_ms"),
                   "peak_ram_mb": max((float(r["peak_ram_mb"]) for r in rs if r.get("peak_ram_mb")), default=None),
                   "last_run": max(r["timestamp"] for r in rs)}
                  for (machine, model), rs in groups.items()]
        return {"rows": len(rows), "models": sorted(models, key=lambda m: m["last_run"], reverse=True)}

    def results_csv(self) -> str:
        path = self.settings.results_dir / "runs.csv"
        return path.read_text() if path.exists() else ""

    # ---------------------------------------------------------------- helpers
    def _allowed_model(self, model: str) -> dict:
        if model not in self.allowed:
            raise BadRequest(f"'{model}' is not on the lab's model list.")
        return self.allowed[model]

    def _agent_model(self, lab_models: list[str]) -> str | None:
        """The configured agent model if it's downloaded, else the biggest downloaded lab model of 1.5B+."""
        if self.settings.agent_model in lab_models:
            return self.settings.agent_model
        usable = [m for m in lab_models if self.allowed[m]["params_b"] >= 1.5]
        return max(usable, key=lambda m: self.allowed[m]["params_b"], default=None)

    def _native(self, path: str) -> str:
        base = self.settings.base_url.rstrip("/")
        return (base[:-3] if base.endswith("/v1") else base) + path


def _step(id, title, *, done, why, does, command=None, kind="action", args=None, link=None) -> dict:
    return {"id": id, "action": id if kind == "action" else None, "kind": kind, "title": title, "done": done,
            "why": why, "does": does, "command": command, "args": args or {}, "link": link}


def _ollama_app() -> str | None:
    if platform.system() == "Darwin":
        for p in (Path("/Applications/Ollama.app"), Path.home() / "Applications" / "Ollama.app"):
            if p.exists():
                return str(p)
    if platform.system() == "Windows":
        p = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama app.exe"
        if p.exists():
            return str(p)
    return shutil.which("ollama")


def _launch(app: str):
    if app.endswith(".app"):
        subprocess.run(["open", "-a", app], check=True, timeout=15)
    elif app.endswith("ollama app.exe"):
        os.startfile(app)  # type: ignore[attr-defined]  # Windows only
    else:
        subprocess.Popen([app, "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


def _num(v):
    return float(v) if v not in (None, "") else None


def _median(rows: list[dict], key: str):
    vals = [float(r[key]) for r in rows if r.get(key) not in (None, "")]
    return round(statistics.median(vals), 1) if vals else None


# -------------------------------------------------------------------- HTTP
def make_handler(lab: Lab, token: str):
    class Handler(BaseHTTPRequestHandler):
        server_version = "LabHelper/0.1"

        def log_message(self, fmt, *args):  # keep the launcher window readable
            pass

        def do_GET(self):
            self._handle("GET")

        def do_POST(self):
            self._handle("POST")

        def _handle(self, method: str):
            port = self.server.server_address[1]
            if self.headers.get("Host") not in (f"127.0.0.1:{port}", f"localhost:{port}"):
                return self._json(403, {"error": "Forbidden host."})
            path = urlparse(self.path).path
            if not path.startswith("/api/"):
                return self._static(path) if method == "GET" else self._json(405, {"error": "Method not allowed."})
            if not secrets.compare_digest(self.headers.get("X-Lab-Token", "").encode(), token.encode()):
                return self._json(401, {"error": "Missing or wrong lab token. Reopen the lab from the Lab Helper window."})
            name = path[len("/api/"):]
            try:
                if method == "GET" and name == "results.csv":
                    return self._send(200, lab.results_csv().encode(), "text/csv; charset=utf-8")
                body = self._body() if method == "POST" else {}
                self._json(200, self._route(method, name, body))
            except BadRequest as e:
                self._json(400, {"error": str(e)})
            except LookupError as e:
                self._json(404, {"error": str(e)})
            except LLMError as e:
                self._json(502, {"error": str(e)})
            except Exception as e:  # never crash the helper; show the learner what happened
                self._json(500, {"error": f"{type(e).__name__}: {e}"})

        def _route(self, method: str, name: str, b: dict):
            if method == "GET":
                if name == "status":
                    return lab.status()
                if name == "results":
                    return lab.results()
                if name.startswith("jobs/") and name[5:] in lab.jobs:
                    return lab.jobs[name[5:]]
            else:
                if name == "recommend":
                    return lab.recommend(str(b.get("goal", "")))
                if name == "plan":
                    return lab.plan(str(b.get("model", "")))
                if name == "jobs":
                    return lab.start_job(str(b.get("action", "")), b.get("args"))
                if name == "chat":
                    return lab.chat(str(b.get("message", "")), bool(b.get("guardrails", True)))
                if name == "chat/reset":
                    return lab.reset_chat()
                if name == "diagnose":
                    return lab.diagnose(str(b.get("text", "")))
                if name == "try":
                    return lab.try_model(str(b.get("model", "")), str(b.get("message", "")))
            raise LookupError(f"No such endpoint: {method} /api/{name}")

        def _body(self) -> dict:
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                raise BadRequest("Request too large.")
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError as e:
                raise BadRequest("Body must be JSON.") from e
            if not isinstance(body, dict):
                raise BadRequest("Body must be a JSON object.")
            return body

        def _static(self, path: str):
            name = "index.html" if path in ("", "/") else path.lstrip("/")
            file = (WEB_DIR / name).resolve()
            if WEB_DIR.resolve() not in file.parents or not file.is_file() or file.suffix not in CONTENT_TYPES:
                return self._json(404, {"error": "Not found."})
            self._send(200, file.read_bytes(), CONTENT_TYPES[file.suffix])

        def _json(self, code: int, payload: dict):
            self._send(code, json.dumps(payload, default=str).encode(), "application/json")

        def _send(self, code: int, data: bytes, ctype: str):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Security-Policy", CSP)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(data)

    return Handler


def create_server(lab: Lab, token: str, port: int = 8765) -> ThreadingHTTPServer:
    """Bind to 127.0.0.1 on the first free port from `port` (port 0 picks any free port)."""
    for p in ([0] if port == 0 else range(port, port + 20)):
        try:
            return ThreadingHTTPServer(("127.0.0.1", p), make_handler(lab, token))
        except OSError:
            continue
    raise SystemExit(f"No free port between {port} and {port + 19}. Close the other Lab Helper window.")


def main(argv=None):
    p = argparse.ArgumentParser(prog="telemetry_agent.helper")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--no-browser", action="store_true", help="don't open the browser")
    args = p.parse_args(argv)

    token = secrets.token_urlsafe(24)
    server = create_server(Lab(), token, args.port)
    url = f"http://127.0.0.1:{server.server_address[1]}/#t={token}"
    print("Local AI Lab helper is running on this laptop only.", flush=True)
    print("Keep this window open while you use the lab. Close it to stop.\n")
    print(f"If the browser didn't open, paste this link into it:\n  {url}\n", flush=True)
    if not args.no_browser:
        threading.Timer(0.5, webbrowser.open, (url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
