"""The agent's five tools.

Each tool's docstring is what the LLM reads to decide when to call it, so the
docstrings are written for the model: when to use the tool, what it returns,
and what NOT to do. The JSON schema for each tool's arguments is declared next
to it in `_PARAMS`.

Safety by design: no tool runs a shell command chosen by the LLM. The tools only
read system facts, call the local model server, or match text against the
error catalog. The learner runs every install command themselves.
"""
from __future__ import annotations

import csv
import json
import re
import shutil
import statistics
import sys
from pathlib import Path

from . import collector, guardrails
from .config import ROOT, Settings, load_allow_list, load_error_catalog
from .llm import ChatClient, LLMError
from .system import hardware_info


class Toolbox:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.allow_list = load_allow_list()
        self.catalog = load_error_catalog()

    # ------------------------------------------------------------------ 1
    def check_hardware(self) -> dict:
        """Report the learner's hardware: OS, CPU architecture and model, CPU cores,
        total and currently available RAM (GB), free disk space (GB), GPU, Python
        version, and whether the terminal is running as administrator.

        Call this before recommending a model, before explaining why a model is slow
        or crashed, or whenever the learner asks what their laptop can handle.
        Never guess hardware specs: always call this tool instead.
        """
        info = hardware_info(self.settings.models_dir)
        if info["running_as_admin"]:
            info["warning"] = "Running as administrator/root. The lab is designed for a normal user account."
        return info

    # ------------------------------------------------------------------ 2
    def check_install(self, up_to_step: int = 5) -> dict:
        """Verify the learner's manual deployment, one tutorial step at a time, and
        report the first step that is not done yet.

        Steps: 1 python (3.9+ works), 2 runtime (Ollama or llama.cpp's llama-server is
        installed), 3 server (the model server answers on its port), 4 model (an
        allow-listed model is downloaded and valid), 5 first_prompt (the model
        replies to a test prompt).

        Call this when the learner asks "did I do it right?", "what's next?", or says
        something isn't working but has no error message. Use `up_to_step` to check
        only the early steps (e.g. 2 while they are still installing the runtime).
        Returns each step's status, a detail message, a safe fix hint for the
        first failing step, and `next_step`.
        """
        s = self.settings
        steps, client, models = [], ChatClient(s.base_url, s.agent_model, timeout=60), []

        def add(n, name, ok, detail, fix=""):
            steps.append({"step": n, "name": name, "ok": ok, "detail": detail, **({"fix": fix} if not ok else {})})
            return ok

        checks = [
            lambda: add(1, "python", sys.version_info >= (3, 9), f"Python {sys.version.split()[0]}",
                        "Install Python 3.9+ from python.org using 'Install for current user'."),
            lambda: self._check_runtime(add),
            lambda: self._check_server(add, client, models),
            lambda: self._check_model(add, models),
            lambda: self._check_first_prompt(add, models),
        ]
        for check in checks[:max(1, min(up_to_step, 5))]:
            if not check():
                break
        failing = next((st for st in steps if not st["ok"]), None)
        return {"runtime": s.runtime, "steps": steps,
                "next_step": failing["name"] if failing else ("benchmark" if len(steps) == 5 else f"step {len(steps) + 1}")}

    def _check_runtime(self, add):
        if self.settings.runtime == "ollama":
            found = shutil.which("ollama") or (Path("/Applications/Ollama.app").exists() and "/Applications/Ollama.app")
            return add(2, "runtime", bool(found), f"Ollama found at {found}" if found else "Ollama not found",
                       "Install Ollama for your user from ollama.com, open it once, then open a new terminal.")
        found = shutil.which("llama-server") or next((str(p) for p in ROOT.rglob("llama-server*") if p.is_file()), None)
        return add(2, "runtime", bool(found), f"llama-server found at {found}" if found else "llama-server not found",
                   "Download the llama.cpp release zip for your CPU (see check_hardware) and unzip it into the project folder.")

    def _check_server(self, add, client, models):
        try:
            models.extend(client.list_models())
            return add(3, "server", True, f"Server at {self.settings.base_url} is up ({len(models)} model(s) available)")
        except LLMError as e:
            fix = ("Open the Ollama app (or run: ollama serve) and leave it running."
                   if self.settings.runtime == "ollama" else
                   "Start the server in its own terminal: ./llama-server -m ./models/<file>.gguf --jinja")
            return add(3, "server", False, str(e), fix)

    def _check_model(self, add, models):
        if self.settings.runtime == "ollama":
            allowed = {m["ollama_tag"] for m in self.allow_list}
            have = [m for m in models if m in allowed]
            return add(4, "model", bool(have),
                       f"Allow-listed models installed: {', '.join(have)}" if have else
                       f"No allow-listed model installed (server has: {', '.join(models) or 'none'})",
                       "Download one with the exact tag, e.g. ollama pull qwen2.5:1.5b (ask for recommend_model first).")
        files = sorted(self.settings.models_dir.glob("*.gguf"))
        if not files:
            return add(4, "model", False, f"No .gguf files in {self.settings.models_dir}",
                       "Download an allow-listed GGUF into the models folder (ask for recommend_model first).")
        bad = [f.name for f in files if _magic(f) != b"GGUF"]  # every GGUF file starts with these 4 bytes
        sizes = ", ".join(f"{f.name} ({f.stat().st_size / 1024**3:.1f} GB)" for f in files)
        if bad:
            return add(4, "model", False, f"Not valid GGUF files: {', '.join(bad)}",
                       "The download is incomplete or the wrong format. Download it again to the same path.")
        return add(4, "model", True, f"GGUF files: {sizes}")

    def _check_first_prompt(self, add, models):
        allowed = {m["ollama_tag"] for m in self.allow_list}
        model = next((m for m in models if m in allowed), models[0] if models else self.settings.agent_model)
        try:
            reply = ChatClient(self.settings.base_url, model, timeout=120).chat(
                [{"role": "user", "content": "Say hello in three words."}], max_tokens=12)
            text = (reply.get("content") or "").strip()
            return add(5, "first_prompt", bool(text), f"{model} replied: {text[:60]!r}",
                       "The server answered but returned no text. Restart it and try again.")
        except LLMError as e:
            return add(5, "first_prompt", False, str(e), "Paste the server window's last lines into read_logs.")

    # ------------------------------------------------------------------ 3
    def run_benchmark(self, model: str, repeats: int = 1,
                      guess_tps: float | None = None, guess_ram_gb: float | None = None) -> dict:
        """Benchmark a downloaded, allow-listed model on this laptop with the team's
        standard method (1 warm-up + 3 standard prompts, streamed, max 128 tokens).
        Returns median time to first token (ms), median tokens per second, average
        CPU % of the machine, peak RAM (MB), model load time (s), and where the
        results file was saved for the dashboard.

        Call this after check_install passes, or when the learner asks how fast a
        model is. `model` must be an allow-listed name exactly as the server lists
        it (e.g. "qwen2.5:1.5b" for Ollama). If the learner predicted the speed or
        memory first, pass `guess_tps` and/or `guess_ram_gb` so the result compares
        their guess with the real numbers. Takes roughly 10-60 seconds.
        """
        if not self._allowed(model):
            return {"error": f"'{model}' is not on the allow-list. Allowed: "
                             + ", ".join(m["ollama_tag"] for m in self.allow_list)}
        repeats = max(1, min(int(repeats), 3))
        try:
            summary = collector.run_benchmark(model, self.settings, repeats=repeats)
        except (LLMError, RuntimeError) as e:
            return {"error": str(e), "hint": "Run check_install to find which step is failing."}
        if guess_tps is not None or guess_ram_gb is not None:
            summary["prediction_check"] = _compare_guess(summary, guess_tps, guess_ram_gb)
        return summary

    def _allowed(self, model: str) -> bool:
        m = model.lower()
        return any(m in (a["ollama_tag"].lower(), a["id"].lower(), a["hf_file"].lower()) for a in self.allow_list)

    # ------------------------------------------------------------------ 4
    def read_logs(self, log_text: str) -> dict:
        """Diagnose an error by matching the learner's pasted terminal output or log
        text against the team's catalog of known local-LLM deployment failures.
        Returns up to 3 likely causes (best first), each with a safe step-by-step
        fix and the concept the learner should understand.

        Call this FIRST whenever the learner pastes an error, a stack trace, or
        server output, before giving any advice of your own. Base your answer on
        the returned fix; do not invent riskier fixes. Pass the text exactly as
        the learner gave it. Secrets such as tokens are removed automatically.
        """
        text = guardrails.redact_secrets(log_text or "")
        scored = []
        for entry in self.catalog:
            hits = [p for p in entry["patterns"] if re.search(p, text, re.IGNORECASE)]
            if hits:
                scored.append((len(hits), entry))
        scored.sort(key=lambda t: -t[0])
        if not scored:
            return {"matches": [], "advice": "No known error matched. Ask the learner for the exact error text "
                                              "(the last 10-20 lines), the command they ran, and their OS."}
        return {"matches": [{"id": e["id"], "title": e["title"], "cause": e["cause"],
                             "fix": e["fix"], "learn": e["learn"]} for _, e in scored[:3]]}

    # ------------------------------------------------------------------ 5
    def recommend_model(self, available_ram_gb: float | None = None, free_disk_gb: float | None = None) -> dict:
        """Recommend an allow-listed model that fits this laptop's free RAM and the
        project's 10 GB disk budget, explain why, and list a faster and a stronger
        alternative. Includes this machine's past benchmark medians when available.

        Call this when the learner asks which model to download or why a model
        crashed or was slow. Leave the arguments empty to use this laptop's live
        hardware; only pass them to answer "what if I had X GB free?". Never
        recommend models that are not in the result.
        """
        hw = hardware_info(self.settings.models_dir)
        # "Available" RAM swings a lot (macOS counts cache as used, and a loaded model holds RAM),
        # so plan on half the total unless more is free right now.
        ram = (available_ram_gb if available_ram_gb is not None
               else round(max(hw["available_ram_gb"], hw["total_ram_gb"] * 0.5), 1))
        disk = free_disk_gb if free_disk_gb is not None else hw["free_disk_gb"]
        disk_cap = min(self.settings.disk_budget_gb, max(disk - 2.0, 0))  # keep 2 GB free for the OS
        fits = [m for m in self.allow_list if m["min_ram_gb"] <= ram and m["size_gb"] <= disk_cap]
        if not fits:
            smallest = min(self.allow_list, key=lambda m: m["min_ram_gb"])
            return {"recommended": None, "planning_ram_gb": ram, "disk_cap_gb": round(disk_cap, 1),
                    "explanation": f"No allow-listed model fits right now. The smallest ({smallest['ollama_tag']}) "
                                   f"needs about {smallest['min_ram_gb']} GB free RAM and {smallest['size_gb']} GB of disk. "
                                   "Close other apps or free disk space, then ask again."}
        comfy = [m for m in fits if m["min_ram_gb"] <= 0.75 * ram]          # leave 25% RAM headroom
        pool = [m for m in comfy if not m["license_gate"]] or comfy or fits  # prefer no license step
        pick = max(pool, key=lambda m: m["params_b"])
        faster = max((m for m in fits if m["params_b"] < pick["params_b"]), key=lambda m: m["params_b"], default=None)
        stronger = min((m for m in fits if m["params_b"] > pick["params_b"]), key=lambda m: m["params_b"], default=None)
        result = {
            "recommended": _brief(pick), "faster_option": _brief(faster), "stronger_option": _brief(stronger),
            "planning_ram_gb": ram, "free_ram_now_gb": hw["available_ram_gb"], "disk_cap_gb": round(disk_cap, 1),
            "explanation": (f"{pick['ollama_tag']} is a {pick['params_b']}B model quantized to {pick['quant']} "
                            f"(~{pick['size_gb']} GB file). It needs about {pick['min_ram_gb']} GB of RAM and you have "
                            f"{ram} GB free, so it leaves headroom for the context and your other apps. "
                            "Bigger models give better answers but load slower, use more RAM, and generate fewer tokens per second."),
            "past_benchmarks_on_this_machine": self._past_benchmarks(hw),
        }
        if available_ram_gb is None and pick["min_ram_gb"] > hw["available_ram_gb"]:
            result["before_you_run"] = (f"Only {hw['available_ram_gb']} GB is free right now. Close big apps "
                                        "(browser tabs, video calls) or other loaded models first.")
        return result

    def _past_benchmarks(self, hw: dict) -> dict:
        path = self.settings.results_dir / "runs.csv"
        if not path.exists():
            return {}
        by_model: dict[str, list[float]] = {}
        with path.open() as f:
            for row in csv.DictReader(f):
                if row.get("cpu_model") == hw["cpu_model"] and row.get("tps"):
                    by_model.setdefault(row["model_name"], []).append(float(row["tps"]))
        return {m: {"median_tps": round(statistics.median(v), 1), "runs": len(v)} for m, v in by_model.items()}

    # ------------------------------------------------------------------ registry
    def call(self, name: str, args: dict) -> dict:
        if name not in _PARAMS:
            return {"error": f"Unknown tool '{name}'. Available: {', '.join(_PARAMS)}"}
        try:
            return getattr(self, name)(**(args or {}))
        except TypeError as e:
            return {"error": f"Bad arguments for {name}: {e}"}

    def schemas(self) -> list[dict]:
        return [{"type": "function", "function": {
            "name": name, "description": _clean_doc(getattr(Toolbox, name).__doc__),
            "parameters": {"type": "object", "properties": props, "required": req}}}
            for name, (props, req) in _PARAMS.items()]


_PARAMS: dict[str, tuple[dict, list[str]]] = {
    "check_hardware": ({}, []),
    "check_install": ({"up_to_step": {"type": "integer", "minimum": 1, "maximum": 5,
                                      "description": "Check steps 1..N (default 5 = all)."}}, []),
    "run_benchmark": ({
        "model": {"type": "string", "description": "Allow-listed model name exactly as the server lists it, e.g. qwen2.5:1.5b"},
        "repeats": {"type": "integer", "minimum": 1, "maximum": 3, "description": "Repeats per prompt (default 1)."},
        "guess_tps": {"type": "number", "description": "Learner's predicted tokens per second, if they made one."},
        "guess_ram_gb": {"type": "number", "description": "Learner's predicted peak RAM in GB, if they made one."},
    }, ["model"]),
    "read_logs": ({"log_text": {"type": "string", "description": "The exact error or terminal output the learner pasted."}},
                  ["log_text"]),
    "recommend_model": ({
        "available_ram_gb": {"type": "number", "description": "Only for what-if questions; omit to use live hardware."},
        "free_disk_gb": {"type": "number", "description": "Only for what-if questions; omit to use live hardware."},
    }, []),
}


def _magic(path: Path) -> bytes:
    with path.open("rb") as f:
        return f.read(4)


def _clean_doc(doc: str | None) -> str:
    return " ".join((doc or "").split())


def _brief(m: dict | None) -> dict | None:
    if not m:
        return None
    return {"name": m["ollama_tag"], "params_billion": m["params_b"], "download_file_size_gb": m["size_gb"],
            "needs_free_ram_gb": m["min_ram_gb"], "requires_license_acceptance": m["license_gate"],
            "hf_repo": m["hf_repo"], "hf_file": m["hf_file"], "good_for": m["good_for"]}


def _compare_guess(summary: dict, guess_tps, guess_ram_gb) -> dict:
    out = {}
    if guess_tps is not None and summary.get("median_tps"):
        real = summary["median_tps"]
        out["tps"] = {"guess": guess_tps, "actual": real, "off_by_percent": round((guess_tps - real) / real * 100)}
    if guess_ram_gb is not None and summary.get("peak_ram_mb"):
        real = round(summary["peak_ram_mb"] / 1024, 2)
        out["ram_gb"] = {"guess": guess_ram_gb, "actual": real, "off_by_percent": round((guess_ram_gb - real) / real * 100)}
    return out
