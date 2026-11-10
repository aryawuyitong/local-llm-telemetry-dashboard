"""Loopback-only lab helper: transparent guided setup, bounded tools, local JSON export.

Run from the agent folder: python -m telemetry_agent.helper
A random launch token stays in the URL fragment and is required on every API call.
Every step shows what it does and its real command. The learner approves it, or runs
it manually and has the helper check. The helper can only start the installed runtime,
download an allow-listed model and undo what it logged. It never runs an installer,
executes a browser/model-selected shell command, or disables an OS security control.
"""
from __future__ import annotations

import argparse
import copy
import dataclasses
import hashlib
import json
import math
import os
import platform
import re
import secrets
import shlex
import shutil
import statistics
import sys
import subprocess
import threading
import time
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from . import answers, guardrails
from .actions import APP_ACTIONS, PAGE_IDS, PLAN, REGISTRY, app_plan, ollama_app, runtime_context
from .apps import APPS, app_context, app_path, install_command, manager as app_manager, remove_command, where_apps_go
from .agent import LabAgent
from .config import ROOT, Settings
from .recipes import load_recipes
from .llm import ChatClient, LLMError
from .router import route
from .tools import Toolbox, _brief, validate_tool_args

WEB_DIR = Path(__file__).resolve().parents[2] / "portal"
CONTENT_TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
                 ".css": "text/css; charset=utf-8", ".json": "application/json", ".woff2": "font/woff2"}
# Only what the website needs, listed once at startup. Tests, notes and licence files are not served.
SITE_FILES = {"/" + p.relative_to(WEB_DIR).as_posix(): p for p in WEB_DIR.rglob("*")
              if p.suffix in CONTENT_TYPES and "tests" not in p.relative_to(WEB_DIR).parts}
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
       "img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
MAX_BODY, MAX_EXPORT_BYTES = 64 * 1024, 10 * 1024**2
DISK_RESERVE_GIB = 2
CONTEXT_SIZES = (2048, 4096, 8192)
TALK_TOKENS, TALK_TURNS, TALK_CHARS = 512, 40, 8000
# The only thing the lab adds to a conversation, and the Use it page says so: this page can't draw maths notation.
TALK_SYSTEM = "Write in plain text. Do not use LaTeX."
from .actions import OLLAMA_DOWNLOAD  # noqa: E402
GOALS = {
    "try": {"label": "Just try it out", "detail": "See a local model work, quickly.", "prefer": "smallest",
            "why": "A smaller model downloads faster and answers sooner. You can add a bigger one later."},
    "study": {"label": "Study help", "detail": "Explain concepts, quiz me.", "prefer": "largest",
              "why": "A balanced pick for your memory. Check its answers, since small models make mistakes."},
    "write": {"label": "Writing", "detail": "Draft and rewrite text.", "prefer": "largest",
              "why": "A balanced pick for your memory. This is based on fit, not a ranking of writing quality."},
    "code": {"label": "Coding help", "detail": "Explain errors, small functions.", "prefer": "stronger",
             "why": "A larger model if it fits. Check any code it writes before you use it."},
}
# Which arguments the page may send for each action the lab can run; the registry is the source.
ACTIONS = {a.id: set(a.args) for a in REGISTRY.values() if a.run}


class BadRequest(ValueError):
    pass


class Busy(RuntimeError):
    pass


def _text(value, name, limit=6000, allow_empty=False):
    if not isinstance(value, str) or len(value) > limit or (not allow_empty and not value.strip()):
        raise BadRequest(f"{name} must be text within the stated length limit.")
    return value.strip()


def _scrub(text):
    text = guardrails.redact_secrets(str(text))
    # Drive letters only count at a word start, so https:// and file:// links survive.
    return re.sub(r"(?:/Users/|/home/|(?<![A-Za-z])[A-Za-z]:[\\/])[^\s\"'<>]+", "[local path omitted]", text)


def _safe_text(value):
    return _scrub(value)[:6000]


class Lab:
    """One learner, one manual lab; inference and jobs are serialized."""

    def __init__(self, settings: Settings | None = None):
        self.settings = dataclasses.replace(settings or Settings(), ram_rule="planning", approval_required=True)
        self.tools = Toolbox(self.settings)
        self.allowed = {m["ollama_tag"]: m for m in self.tools.allow_list}
        self.jobs = {}
        self._agents = {}
        self._jobs_lock = threading.RLock()
        self._operation_lock = threading.Lock()
        self._chat_lock = threading.Lock()
        self.talks = {}
        self.setups = load_recipes()
        self._talked_with = set()

    def status(self):
        runtime = self.runtime_state()
        model = self._agent_model(runtime["lab_models"])
        return {"runtime": runtime, "installation_mode": "guided",
                "assistant": {"ready": bool(model), "model": model, "wanted_model": self.settings.agent_model,
                              "guardrails_required": True, "comparison_mode": "Use the isolated text-only evaluation harness."},
                "platform_validation": "Windows implementation has automated tests, but no physical Windows validation is claimed.",
                "goals": {k: {"label": g["label"], "detail": g["detail"]} for k, g in GOALS.items()}}

    def runtime_state(self):
        client = ChatClient(self.settings.base_url, self.settings.agent_model)
        try:
            listed = client.list_models()
            running = True
        except LLMError:
            listed, running = [], False
        # Ollama's list is only its manifests. A model whose file is gone stays listed but can't load,
        # so "installed" here means the file is really on disk.
        broken = client.missing_files(listed) if running else []
        models = [m for m in listed if m not in broken]
        binary = "ollama" if self.settings.runtime == "ollama" else "llama-server"
        installed = running or bool(shutil.which(binary))
        if self.settings.runtime == "ollama" and platform.system() == "Darwin":
            installed = installed or any(p.is_dir() for p in (Path("/Applications/Ollama.app"), Path.home() / "Applications/Ollama.app"))
        folder = self.settings.runtime_models_dir
        return {"name": "Ollama" if self.settings.runtime == "ollama" else "llama.cpp (experimental)",
                "installed": bool(installed), "running": running, "models": models, "broken_models": broken,
                "lab_models": [m for m in models if m in self.allowed], "download_url": OLLAMA_DOWNLOAD,
                "models_dir": str(folder), "models_dir_exists": folder.is_dir()}

    def _planning_ram(self, hw):
        return max(hw["available_ram_gb"], hw["total_ram_gb"] * 0.5) if hw["available_ram_gb"] >= 1 else hw["available_ram_gb"]

    def compatibility(self):
        """A plain answer for every approved model, before anything is downloaded."""
        hw = self.tools.check_hardware()
        rt = self.runtime_state()
        installed, broken = set(rt["models"]), set(rt.get("broken_models", []))
        models = []
        for m in sorted(self.allowed.values(), key=lambda x: x["params_b"]):
            have = m["ollama_tag"] in installed
            if not have and hw["free_disk_gb"] - m["size_gb"] < DISK_RESERVE_GIB:
                verdict, reason = "no", f"Needs about {m['size_gb']} GB of disk, and only {hw['free_disk_gb']} GB is free."
            elif hw["available_ram_gb"] >= m["min_ram_gb"]:
                verdict, reason = "yes", f"You have enough free memory (about {m['min_ram_gb']} GB needed)."
            elif self._planning_ram(hw) >= m["min_ram_gb"]:
                verdict, reason = "close_apps", f"Needs about {m['min_ram_gb']} GB free. Close some apps first."
            else:
                verdict, reason = "no", f"Needs about {m['min_ram_gb']} GB free, and this laptop has {hw['total_ram_gb']} GB in total."
            models.append({"name": m["ollama_tag"], "params_b": m["params_b"], "size_gb": m["size_gb"], "quant": m["quant"],
                           "min_ram_gb": m["min_ram_gb"], "license_gate": m["license_gate"], "installed": have,
                           "missing_file": m["ollama_tag"] in broken, "verdict": verdict, "reason": reason})
        return {"models": models, "free_ram_gb": hw["available_ram_gb"], "total_ram_gb": hw["total_ram_gb"],
                "free_disk_gb": hw["free_disk_gb"]}

    def _changes_path(self):
        return self.settings.results_dir / "changes" / "log.json"

    def changes(self):
        try:
            data = json.loads(self._changes_path().read_text(encoding="utf-8"))
            return {"changes": data if isinstance(data, list) else []}
        except (OSError, ValueError):
            return {"changes": []}

    def _log_change(self, what, undo_model=None, kind="change", undo_app=None):
        """kind: "change" altered the laptop; "check" and "assistant" only record what the agent did."""
        with self._jobs_lock:
            items = self.changes()["changes"]
            items.append({"when": time.strftime("%Y-%m-%d %H:%M"), "what": what, "undo_model": undo_model, "undo_app": undo_app,
                          "undone": False, "kind": kind})
            path = self._changes_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(items[-200:], indent=1), encoding="utf-8")

    def show_model(self, model):
        """Open the model's file in Finder or File Explorer, and return where it is. The log never stores the path."""
        self._allowed_model(model)
        if self.settings.runtime != "ollama" or model not in self.runtime_state()["lab_models"]:
            raise BadRequest("Download this model first, then it will have a place on your laptop.")
        path = Path(ChatClient(self.settings.base_url, model).model_file(model))
        # Only ever open what Ollama reports as a model file, whatever the response says.
        if path.parent.name != "blobs" or not re.fullmatch(r"sha256-[0-9a-f]{64}", path.name) or not path.is_file():
            raise BadRequest("Ollama reported a location that isn't a model file, so the lab won't open it.")
        try:
            _reveal(path)
            opened = True
        except (OSError, subprocess.SubprocessError):
            opened = False
        self._log_change(f"Showed you where {model} is stored.", kind="check")
        return {"model": model, "path": str(path), "folder": str(path.parent), "size_gb": round(path.stat().st_size / 1024**3, 2), "opened": opened}

    def show_models_folder(self):
        """Open Ollama's models folder in Finder or File Explorer, so a learner never has to search for it."""
        folder = self.settings.runtime_models_dir
        if not folder.is_dir():
            raise BadRequest("Ollama hasn't created its models folder yet. It appears after the first download.")
        try:
            _open_folder(folder)
            opened = True
        except (OSError, subprocess.SubprocessError):
            opened = False
        self._log_change("Showed you Ollama's models folder.", kind="check")
        return {"folder": str(folder), "opened": opened}

    def recommend(self, goal):
        if not isinstance(goal, str) or goal not in GOALS:
            raise BadRequest("Choose one of the listed goals.")
        hw = self.tools.check_hardware()
        rec = self.tools.recommend_model(available_ram_gb=self._planning_ram(hw))
        pick, options = self._goal_pick(goal)
        return {**rec, "goal": goal, "goal_why": GOALS[goal]["why"], "pick": pick, "options": options}

    def _goal_pick(self, goal):
        """Prefer models ready right now and with no license step; `prefer` says which end of that list suits the goal."""
        models = [m for m in self.compatibility()["models"] if m["verdict"] != "no" and not m["license_gate"]]
        ready = [m for m in models if m["verdict"] == "yes"]
        tutors = [m for m in (ready or models) if m["params_b"] >= 1.5] or ready or models
        if not tutors:
            return None, []
        choice = {"smallest": tutors[0], "largest": tutors[-1], "stronger": (models[-1] if len(models) > 1 else tutors[-1])}[GOALS[goal]["prefer"]]
        at = models.index(choice)
        nearby = models[max(0, at - 1):at + 2]
        return _brief(self.allowed[choice["name"]]), [_brief(self.allowed[m["name"]]) for m in nearby]

    def plan(self, model):
        m = self._allowed_model(model)
        if self.settings.runtime != "ollama":
            return {"model": _brief(m), "installation_mode": "guided", "steps": [],
                    "supported_stop": "This build has not verified a llama.cpp model-provenance path. Use the supported Ollama lab or ask the team."}
        ctx = runtime_context(m, self.runtime_state())
        steps = [REGISTRY[a].step(ctx) for a in PLAN]
        for step in steps:
            step["id"] = PAGE_IDS.get(step["id"], step["id"])
        return {"model": _brief(m), "installation_mode": "guided", "steps": steps}

    def risks(self):
        """Labels for the two cards the page draws itself. They come from the registry like every other card."""
        model = min(self.allowed.values(), key=lambda m: m["params_b"])
        ctx = runtime_context(model, {"installed": True, "running": True, "models": [], "broken_models": []})
        return {action: REGISTRY[action].step(ctx)["risk"] for action in ("check_hardware", "benchmark")}

    def describe_action(self, action, args):
        """The approval card for one registered action, e.g. one the assistant proposes. Never runs it."""
        if action not in REGISTRY or REGISTRY[action].kind != "action":
            raise BadRequest("Unknown action.")
        if action in APP_ACTIONS:
            ctx = app_context(self._allowed_app(args.get("app")))
        else:
            model = self._allowed_model(args["model"]) if "model" in args else None
            ctx = runtime_context(model, self.runtime_state())
        step = REGISTRY[action].step(ctx)
        step["args"] = {**step["args"], **{k: v for k, v in args.items() if k in ACTIONS[action]}}
        return step

    # ---------------------------------------------------------------- apps: the second provider
    def _allowed_app(self, app):
        if not isinstance(app, str) or app not in APPS:
            raise BadRequest("Choose one of the lab's listed apps.")
        return app

    def apps(self):
        """The apps page: what the lab can install here, what is already there, and which installer this laptop has."""
        undoable = {c.get("undo_app") for c in self.changes()["changes"] if c.get("undo_app") and not c.get("undone")}
        rows = []
        for app in APPS.values():
            path = app_path(app)
            rows.append({"id": app["id"], "name": app["name"], "what": app["what"], "why": app["why"], "size_gb": app["size_gb"],
                         "site": app["site"], "installed": bool(path), "path": str(path) if path else None, "by_lab": app["id"] in undoable})
        return {"apps": rows, "manager": app_manager()}

    def plan_app(self, app):
        ctx = app_context(self._allowed_app(app))
        return {"app": {"id": app, "name": ctx["name"], "size_gb": ctx["app"]["size_gb"]}, "manager": ctx["manager"],
                "steps": [REGISTRY[a].step(ctx) for a in app_plan(ctx)]}

    def _run_command(self, job, command, timeout=900):
        """Run exactly the command the card showed, line by line into the step's log. Never a shell, never a password prompt."""
        argv = shlex.split(command, posix=platform.system() != "Windows")
        proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, errors="replace", start_new_session=True)
        watchdog = threading.Timer(timeout, proc.kill)
        watchdog.start()
        try:
            for line in proc.stdout:
                line = _safe_text(line.rstrip())
                if line:
                    job["log"].append(line)
                    del job["log"][:-80]
            code = proc.wait()
        finally:
            watchdog.cancel()
        if code != 0:
            tail = " ".join(job["log"][-3:])
            raise RuntimeError(f"The installer stopped with exit code {code}. Last lines: {tail}" if tail else f"The installer stopped with exit code {code}.")

    def _do_install_app(self, job, app):
        ctx = app_context(app)
        name, m = ctx["name"], ctx["manager"]
        if ctx["installed_at"]:
            job["log"].append(f"{name} is already installed.")
            return {"app": app, "installed": True, "path": ctx["installed_at"], "already": True}
        if not m["installed"]:
            raise RuntimeError(f"{m['name']} isn't on this laptop, so the lab can't install {name} for you. Use the official download page in the step instead.")
        command = install_command(ctx)
        job["log"].append(f"Running: {command}")
        start = time.perf_counter()
        self._run_command(job, command)
        path = app_path(ctx["app"])
        if not path:
            raise RuntimeError(f"{m['name']} finished, but {name} isn't in {where_apps_go(ctx)}. Run the command in a terminal to see what it says.")
        self._log_change(f"Installed {name} with {m['name']}, about {ctx['app']['size_gb']} GB, in {where_apps_go(ctx)}.", undo_app=app)
        return {"app": app, "installed": True, "path": str(path), "seconds": round(time.perf_counter() - start, 1)}

    def _do_check_app(self, job, app):
        ctx = app_context(app)
        m, path = ctx["manager"], ctx["installed_at"]
        steps = [{"ok": m["installed"], "detail": f"{m['name']} is on this laptop." if m["installed"] else f"{m['name']} is not on this laptop (you installed the app yourself, or still need to)."},
                 {"ok": bool(path), "detail": f"{ctx['name']} is in {where_apps_go(ctx)}: {path}" if path else f"{ctx['name']} is not in {where_apps_go(ctx)}."}]
        if not path:
            raise RuntimeError(f"{ctx['name']} is not in {where_apps_go(ctx)}. Approve the install step, or install it from the official page, then check again.")
        return {"app": app, "installed": True, "path": path, "steps": steps}

    def _do_remove_app(self, job, app):
        ctx = app_context(app)
        with self._jobs_lock:
            items = self.changes()["changes"]
            logged = [c for c in items if c.get("undo_app") == app and not c.get("undone")]
            if not logged:
                raise RuntimeError("Only an app this lab installed can be removed here.")
        if ctx["installed_at"]:
            if not ctx["manager"]["installed"]:
                raise RuntimeError(f"{ctx['manager']['name']} isn't on this laptop any more, so remove {ctx['name']} the way you'd remove any app.")
            command = remove_command(ctx)
            job["log"].append(f"Running: {command}")
            self._run_command(job, command)
            if app_path(ctx["app"]):
                raise RuntimeError(f"The uninstaller finished, but {ctx['name']} is still in {where_apps_go(ctx)}.")
        else:
            job["log"].append(f"{ctx['name']} was already gone.")
        with self._jobs_lock:
            for change in logged:
                change["undone"] = True
            items.append({"when": time.strftime("%Y-%m-%d %H:%M"), "what": f"Removed {ctx['name']} (undo).", "undo_model": None, "undo_app": None, "undone": False})
            self._changes_path().write_text(json.dumps(items[-200:], indent=1), encoding="utf-8")
        job["log"].append(f"Removed {ctx['name']}.")
        return {"app": app, "removed": True}

    # ---------------------------------------------------------------- receipt
    def receipt(self):
        """One page the learner keeps: everything the lab added, where, how big, and how to remove each item."""
        rt = self.runtime_state()
        log = self.changes()["changes"]
        made = time.strftime("%Y-%m-%d %H:%M")
        lines = ["# Local AI Lab receipt", "",
                 f"Made {made} on this laptop ({platform.system()} {platform.release()}).", "",
                 "Everything the lab added to this laptop, where it is, how much space it takes, and how to remove each item. "
                 "The lab never asked for your password, changed a setting, or sent anything off this laptop. "
                 "This page names folders on your laptop, so keep it for yourself.", ""]
        total = 0.0
        lines += ["## Models", ""]
        if rt["lab_models"]:
            for tag in rt["lab_models"]:
                size, where = None, rt["models_dir"]
                try:
                    path = Path(ChatClient(self.settings.base_url, tag).model_file(tag))
                    size, where = path.stat().st_size / 1024**3, str(path)
                except (LLMError, OSError):
                    pass
                total += size or 0
                by_lab = any(c.get("undo_model") == tag and not c.get("undone") for c in log)
                lines.append(f"- **{tag}**: {f'{size:.2f} GB' if size is not None else 'size unknown'} at `{where}`"
                             + (" (downloaded by this lab)" if by_lab else " (was already here)")
                             + f". Remove: Undo in My lab, or `ollama rm {tag}`.")
        else:
            lines.append("- None.")
        if rt.get("broken_models"):
            lines.append(f"- Listed by Ollama but with no file on disk, so they take no space: {', '.join(rt['broken_models'])}. Tidy with `ollama rm NAME`.")
        lines += ["", "## Apps", ""]
        apps = [a for a in self.apps()["apps"] if a["by_lab"]]
        for a in apps:
            total += a["size_gb"]
            lines.append(f"- **{a['name']}**: about {a['size_gb']} GB at `{a['path']}`. Remove: Undo in My lab, or `{remove_command(app_context(a['id']))}`.")
        if not apps:
            lines.append("- None installed by this lab.")
        lines += ["", "## The lab itself", ""]
        for label, path, undo in (("The lab's private Python environment", ROOT / ".venv", "delete the folder"),
                                  ("A private copy of Python", ROOT / ".python", "delete the folder"),
                                  ("Your measurements and this log", self.settings.results_dir, "delete the folder")):
            if path.is_dir():
                size = _folder_size(path)
                total += size
                lines.append(f"- {label}: {size:.2f} GB at `{path}`. Remove: {undo}.")
        lines.append("- Ollama itself: " + ("installed by you from its official page. Remove it the way you'd remove any app." if rt["installed"] else "not installed."))
        lines += ["", f"**Space in all: about {total:.1f} GB.**", "", "## What the lab did", ""]
        counts = {k: sum(1 for c in log if (c.get("kind") or "change") == k) for k in ("change", "check", "assistant")}
        lines.append(f"- {counts['change']} steps changed this laptop, {counts['check']} only read or measured, and the assistant used tools {counts['assistant']} times. "
                     f"Every one is listed in My lab with its time.")
        undone = [c["what"] for c in log if c.get("undone")]
        if undone:
            lines.append(f"- Undone since: {len(undone)}.")
        return {"markdown": "\n".join(lines) + "\n", "filename": f"local-ai-lab-receipt-{time.strftime('%Y-%m-%d')}.md"}

    def start_job(self, action, args=None):
        if not isinstance(action, str) or action not in ACTIONS:
            raise BadRequest("Unknown or unsupported action. Only the lab's fixed steps can run.")
        if args is None:
            args = {}
        if not isinstance(args, dict) or set(args) - ACTIONS[action]:
            raise BadRequest("Arguments must be an object containing only the action's documented keys.")
        args = dict(args)
        if "model" in ACTIONS[action] and (action != "check_install" or "model" in args):
            self._allowed_model(args.get("model"))
        if "app" in ACTIONS[action]:
            self._allowed_app(args.get("app"))
        if "recipe" in ACTIONS[action]:
            self._allowed_recipe(args.get("recipe"))
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
            result = getattr(self, REGISTRY[job["action"]].run)(job, **job["args"])
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
        self._log_job(job)

    def _log_job(self, job):
        """Record checks and measurements; steps that change the laptop log themselves as they finish."""
        done = job.get("status") in {"done", "partial"}
        what = REGISTRY[job["action"]].log(job["args"], job.get("result") or {}, done)
        if what:
            try:
                self._log_change(what if done else what.rstrip(".") + " (failed).", kind="check")
            except OSError:
                pass  # the log must never break the step itself

    def _do_check_hardware(self, job):
        job["log"].append("Reading this laptop's hardware and account privilege level.")
        return self.tools.check_hardware()

    def _do_check_install(self, job, up_to_step=4, model=None):
        result = self.tools.check_install(up_to_step, model)
        if result["steps"] and not result["steps"][-1]["ok"]:
            raise RuntimeError(result["steps"][-1]["detail"] + " " + result["steps"][-1].get("fix", ""))
        return result

    def _do_start_runtime(self, job):
        if self.runtime_state()["running"]:
            job["log"].append("Ollama is already running.")
            return {"running": True}
        app = ollama_app()
        if not app:
            raise RuntimeError("ollama: command not found. Install Ollama first, using the step above.")
        job["log"].append("Opening Ollama.")
        _launch(app)
        for _ in range(40):
            time.sleep(0.75)
            if self.runtime_state()["running"]:
                job["log"].append("Ollama is running on this laptop, at port 11434.")
                self._log_change("Started Ollama. Quit it from its menu bar or system tray icon.")
                return {"running": True}
        raise RuntimeError("Could not connect to Ollama: it didn't start within 30 seconds. Open the app yourself, then check again.")

    def _do_pull_model(self, job, model):
        size = self.allowed[model]["size_gb"]
        state = self.tools.budget_state()
        free = shutil.disk_usage(Path.home()).free / 1024**3
        if free - size < DISK_RESERVE_GIB:
            raise RuntimeError(f"No space left on device: {model} needs about {size} GB and {free:.1f} GB is free. We keep {DISK_RESERVE_GIB} GB for your system.")
        if state["non_model_gib"] + size > self.settings.disk_budget_gb:
            raise RuntimeError("This model would take the lab past its disk budget. Choose a smaller approved model.")
        was_present = model in self.runtime_state()["models"]
        last = None
        for item in ChatClient(self.settings.base_url, model).pull_stream(model):
            if item.get("error"):
                raise RuntimeError(str(item["error"]))
            status = str(item.get("status", ""))
            if item.get("total"):
                done = item.get("completed", 0)
                job["progress"] = round(done / item["total"], 3)
                job["detail"] = f"{done / 1024**3:.2f} of {item['total'] / 1024**3:.2f} GB"
            label = "Downloading model files" if status.startswith("pulling ") and status != "pulling manifest" else status
            if label and label != last:
                job["log"].append(label)
                last = label
        if last != "success":
            raise RuntimeError("The download stopped before it finished. Approve it again to resume.")
        if not was_present:
            self._log_change(f"Downloaded {model}, about {size} GB, to Ollama's models folder.", undo_model=model)
        return {"model": model, "downloaded": True}

    def _do_remove_model(self, job, model):
        with self._jobs_lock:
            items = self.changes()["changes"]
            logged = [c for c in items if c.get("undo_model") == model and not c.get("undone")]
            if not logged:
                raise RuntimeError("Only a model this lab downloaded can be removed here.")
        ChatClient(self.settings.base_url, model).delete_model(model)
        with self._jobs_lock:
            for change in logged:
                change["undone"] = True
            items.append({"when": time.strftime("%Y-%m-%d %H:%M"), "what": f"Removed {model} (undo).", "undo_model": None, "undone": False})
            self._changes_path().write_text(json.dumps(items[-200:], indent=1), encoding="utf-8")
        job["log"].append(f"Removed {model}.")
        return {"model": model, "removed": True}

    def _do_first_prompt(self, job, model):
        self.tools.ensure_model_ready(model)
        job["log"].append("Running a bounded first prompt after provenance and project-budget checks.")
        start = time.perf_counter()
        reply = ChatClient(self.settings.base_url, model, timeout=120).chat(
            [{"role": "user", "content": "Say hello in three words."}], max_tokens=12)
        text = (reply.get("content") or "").strip()
        if not text:
            raise RuntimeError("The local model returned no text.")
        return {"reply": _safe_text(text), "seconds": round(time.perf_counter() - start, 2)}

    def _do_benchmark(self, job, model, repeats=3, guess_tps=None, guess_ram_gb=None):
        job["log"].append("Warm-up, then three fixed prompts and three measured repetitions per prompt by default.")
        result = self.tools.measure_now(model, repeats=repeats, guess_tps=guess_tps, guess_ram_gb=guess_ram_gb)
        if result.get("error"):
            raise RuntimeError(result["error"])
        if result.get("saved_to"):
            result["saved_to"] = Path(result["saved_to"]).name
        job["log"].append("Session saved locally; download the anonymous JSON in Results.")
        return result

    def chat(self, text, guardrails_on=True, open_question=False):
        """open_question is the page's "Not what I asked" button: go straight to the model, and say so."""
        text = _text(text, "message")
        if type(guardrails_on) is not bool or not guardrails_on:
            raise BadRequest("Live helper safety stays on. Use the isolated evaluation harness for the text-only comparison.")
        # Facts come from code. A pasted secret skips this, so the agent can warn about it first.
        no_secret = guardrails.redact_secrets(text) == text
        if no_secret and not open_question:
            checked = answers.answer(self, text)
            if checked:
                return self._checked_reply(checked)
        model = self._agent_model(self.runtime_state()["lab_models"])
        if not model:
            # Rule-based bootstrap: no nonexistent model or hidden cloud dependency.
            return {"text": self._bootstrap_text(text),
                    "model": None, "guardrails": True, "guardrail_intervened": False, "flagged": [],
                    "trace": [], "mode": "static_bootstrap"}
        if not self._operation_lock.acquire(blocking=False):
            raise Busy("A lab operation is running. Wait so tutoring does not contaminate the benchmark.")
        try:
            try:
                self.tools.ensure_model_ready(model)
            except ValueError as exc:
                # The assistant must not go silent at the moment help is needed most.
                return {"text": f"{exc}\n\n{self._bootstrap_text(text)}", "model": None, "guardrails": True,
                        "guardrail_intervened": False, "flagged": [], "trace": [], "mode": "rule_only"}
            if no_secret and not open_question:
                chosen = answers.pick(self, model, text)
                if chosen:
                    return self._checked_reply(chosen)
            with self._chat_lock:
                if model not in self._agents:
                    self._agents[model] = LabAgent(dataclasses.replace(self.settings, guardrails=True, agent_model=model, open_answers=True))
                agent = self._agents[model]
                if len(agent.messages) > 80:
                    agent.reset()
                # The agent owns pre-model redaction and must see that a secret
                # was pasted so it can also explain revocation/change guidance.
                try:
                    reply = agent.ask(text)
                except LLMError as exc:
                    # The model didn't answer. If Ollama's message is a known problem, give its fix;
                    # otherwise give the rule-based answer. The page offers a retry either way.
                    known = self.tools.read_logs(str(exc))["matches"]
                    if known:
                        lead = (f"The local model didn't answer. Ollama said: {exc}\n\n{known[0]['title']}: {known[0]['cause']}\n"
                                + "\n".join(known[0]["fix"]))
                    else:
                        lead = f"I couldn't reach the local model just now ({exc}). Make sure Ollama is open, then try again.\n\n" + self._bootstrap_text(text)
                    return {"text": _safe_text(lead), "model": model, "guardrails": True, "guardrail_intervened": False,
                            "flagged": [], "trace": [], "mode": "rule_only", "retry": True}
            proposals = []
            for step in reply.trace:
                self._log_change(f"The assistant used {step['tool']} ({'the AI' if step['chosen_by'] == 'llm' else 'a rule'} chose it).", kind="assistant")
                proposed = step["result"].get("proposed") if isinstance(step["result"], dict) else None
                if proposed:
                    try:
                        proposals.append(self.describe_action(proposed["action"], proposed.get("args") or {}))
                    except (BadRequest, KeyError, TypeError):
                        pass  # a malformed proposal is dropped, never shown
            return {"text": _safe_text(reply.text), "model": model, "guardrails": True, "proposals": proposals,
                    "guardrail_intervened": reply.guardrail_intervened,
                    "flagged": sorted({v.rule for v in reply.raw_violations}),
                    "trace": [{"tool": s["tool"], "args": _safe_text(json.dumps(s["args"])),
                               "chosen_by": s["chosen_by"], "result": _safe_text(json.dumps(s["result"], default=str))[:1500]}
                              for s in reply.trace], "mode": "local_model"}
        finally:
            self._operation_lock.release()

    def _checked_reply(self, checked):
        """A reply code wrote. It carries real paths on purpose: they come from this laptop, not from a model."""
        proposals = []
        for action, args in checked["proposals"]:
            try:
                proposals.append(self.describe_action(action, args))
            except (BadRequest, KeyError, TypeError):
                pass  # a malformed proposal is dropped, never shown
        try:
            self._log_change(f"The assistant answered from {'a check' if checked['kind'] == 'checked' else 'its notes'} ({checked['id']}).", kind="assistant")
        except OSError:
            pass
        return {"text": checked["text"], "model": None, "guardrails": True, "proposals": proposals, "guardrail_intervened": False,
                "flagged": [], "trace": [], "mode": checked["kind"], "checked": checked["checked"], "links": checked["links"], "picked_by": checked.get("picked_by")}

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
        for name, _ in route(text, list(self.allowed)):
            if name == "recommend_model":
                fits = [m for m in self.compatibility()["models"] if m["verdict"] != "no"]
                return "Models that fit this laptop: " + (", ".join(m["name"] for m in fits) or "none right now") + ". Set up shows the reason for each."
            if name == "check_hardware":
                hw = self.tools.check_hardware()
                return f"{hw['os']}, {hw['cpu_model']}, {hw['total_ram_gb']} GB of memory with {hw['available_ram_gb']} GB free right now, and {hw['free_disk_gb']} GB of free disk."
            if name == "check_install":
                steps = self.tools.check_install(4)
                return "Next step: " + steps["next_step"].replace("_", " ") + ". " + (steps["steps"][-1].get("fix") or steps["steps"][-1]["detail"])
        lower = text.lower()
        if "token" in lower or "tps" in lower or "throughput" in lower:
            return "Tokens are text pieces chosen by the model's tokenizer. Decode TPS is generated tokens divided by runtime-reported generation seconds. The lab's first-text latency is a client-observed proxy, since a streamed text chunk can contain more than one token. Follow Deploy to prepare a real model before measuring."
        if "ram" in lower or "memory" in lower:
            return "Model weights, runtime state and conversation/context use memory. Available RAM right now matters; total installed RAM is not the amount free for a new model. Check your hardware and the provisional model estimates in Deploy."
        if "local" in lower or "cloud" in lower or "runtime" in lower:
            return "A language model is a set of learned weights. A runtime loads those weights and performs inference. Local inference runs on your laptop; cloud inference runs on a remote service. This lab uses a loopback-only local runtime and does not send your questions to a cloud model."
        if "quant" in lower:
            return "Quantization represents model weights using fewer bits to reduce storage and memory. Its quality and speed effects depend on the exact model, artifact and device. A catalog GGUF format does not prove the quantization of an Ollama tag."
        return "The local model isn't available to answer that right now. Follow the Set up steps, or paste a short error for help from our list of known problems. This answer comes from fixed rules, not an AI model."

    def try_model(self, model, message, context_tokens=2048):
        self._allowed_model(model)
        if context_tokens not in CONTEXT_SIZES or type(context_tokens) is not int:
            raise BadRequest("Choose one of the listed context sizes.")
        message = guardrails.redact_secrets(_text(message, "message", 2000))
        if not self._operation_lock.acquire(blocking=False):
            raise Busy("Wait for the current lab operation before generating text.")
        try:
            self.tools.ensure_model_ready(model)
            start, first, parts, tokens, duration = time.perf_counter(), None, [], None, None
            for ts, delta, usage in ChatClient(self.settings.base_url, model, timeout=120).benchmark_stream(
                    [{"role": "user", "content": message}], runtime=self.settings.runtime,
                    max_tokens=128, temperature=0, context_tokens=context_tokens):
                if delta:
                    first = ts if first is None else first
                    parts.append(delta)
                if usage and usage.get("completion_tokens") is not None:
                    count = usage["completion_tokens"]
                    if type(count) is not int or not 0 <= count <= 128:
                        raise ValueError("The local runtime returned an invalid output-token count.")
                    tokens = count
                if usage and usage.get("source") == "ollama_native":
                    count, nanos = usage.get("eval_count"), usage.get("eval_duration")
                    if count is not None and (type(count) is not int or not 0 <= count <= 128):
                        raise ValueError("The local runtime returned an invalid decode-token count.")
                    if count is not None:
                        tokens = count
                    if nanos is not None and (type(nanos) not in (int, float) or not 0 < nanos <= 10**15 or not math.isfinite(nanos)):
                        raise ValueError("The local runtime returned an invalid decode duration.")
                    if nanos is not None:
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

    # ---------------------------------------------------------------- health check and help report
    def _card(self, action, args):
        try:
            return self.describe_action(action, args)
        except (BadRequest, KeyError, TypeError):
            return None

    def health(self):
        """Re-run every check, and offer a repair card for what can be repaired. It only reads; nothing runs from here."""
        hw = self.tools.check_hardware()
        rt = self.runtime_state()
        log = self.changes()["changes"]
        checks = []

        def add(id_, label, status, detail, repair=None, repairs=None, goto=None):
            checks.append({"id": id_, "label": label, "status": status, "detail": detail, "repair": repair, "repairs": [r for r in (repairs or []) if r], "goto": goto})

        python_ok = sys.version_info >= (3, 11)
        add("python", "Python", "ok" if python_ok else "bad", f"Python {platform.python_version()} is running the lab." + ("" if python_ok else " The lab needs 3.11 or newer."))
        try:
            self.settings.results_dir.mkdir(parents=True, exist_ok=True)
            probe = self.settings.results_dir / f".health-{uuid.uuid4().hex[:8]}"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            add("lab_folder", "The lab's folder", "ok", "The lab can save its results and log.")
        except OSError:
            add("lab_folder", "The lab's folder", "bad", "The lab can't write to its results folder, so it can't save anything. Try moving the lab out of a synced or protected folder.")
        low_disk = hw["free_disk_gb"] < DISK_RESERVE_GIB + 1
        add("disk", "Free disk", "warn" if low_disk else "ok", f"{hw['free_disk_gb']} GB free." + (" That's low: downloads may fail. Free some space, or use Undo in My lab." if low_disk else ""))
        add("ollama_installed", "Ollama installed", "ok" if rt["installed"] else "bad", "Ollama is installed." if rt["installed"] else "Ollama isn't installed. Set up walks you through it.",
            goto=None if rt["installed"] else "deploy")
        if rt["installed"]:
            add("ollama_running", "Ollama running", "ok" if rt["running"] else "bad", "Ollama is running and answering." if rt["running"] else "Ollama isn't running, so no model can answer.",
                repair=None if rt["running"] else self._card("start_runtime", {}))
        if rt["running"]:
            if rt["lab_models"]:
                add("models", "Models", "ok", f"On this laptop, with their files: {', '.join(rt['lab_models'])}.")
            else:
                add("models", "Models", "warn", "No model has its file on this laptop.", goto="catalog")
            broken = rt.get("broken_models") or []
            add("model_files", "Model files", "warn" if broken else "ok",
                f"Ollama lists these, but their files are gone, so they can't run: {', '.join(broken)}." if broken else "Every model Ollama lists has its file.",
                repairs=[self._card("pull_model", {"model": m}) for m in broken if m in self.allowed])
            owed = [c["undo_model"] for c in log if c.get("undo_model") and not c.get("undone")]
            gone = [m for m in dict.fromkeys(owed) if m not in rt["models"] and m not in broken]
            add("lab_models_present", "What the lab downloaded", "warn" if gone else "ok",
                f"The lab downloaded these, and they've since gone: {', '.join(gone)}. You may have removed them yourself." if gone else "Everything the lab downloaded is still here.",
                repairs=[self._card("pull_model", {"model": m}) for m in gone if m in self.allowed])
            enough = bool(rt["lab_models"]) and min(self.allowed[m]["min_ram_gb"] for m in rt["lab_models"]) <= hw["available_ram_gb"]
            if rt["lab_models"]:
                add("memory", "Free memory", "ok" if enough else "warn",
                    f"{hw['available_ram_gb']} GB free of {hw['total_ram_gb']} GB." + ("" if enough else " That's less than your smallest model wants. Close some apps."))
                smallest = min(rt["lab_models"], key=lambda m: self.allowed[m]["params_b"])
                add("reply", "A model's reply", "optional",
                    "This check doesn't test that, because it would load a model into memory. Approve this card to test it.", repair=self._card("first_prompt", {"model": smallest}))
        owed_apps = [c["undo_app"] for c in log if c.get("undo_app") and not c.get("undone") and c["undo_app"] in APPS]
        lost = [APPS[a]["name"] for a in dict.fromkeys(owed_apps) if not app_path(APPS[a])]
        add("lab_apps_present", "Apps the lab installed", "warn" if lost else "ok",
            f"The lab installed these, and they've since gone: {', '.join(lost)}. You may have removed them yourself." if lost else ("Every app the lab installed is still here." if owed_apps else "The lab hasn't installed any apps."),
            goto="catalog" if lost else None)
        with self._jobs_lock:
            failed = [j for j in self.jobs.values() if j["status"] == "failed"]
        if failed:
            add("last_failure", "Last failed step", "warn", f"{failed[-1]['action']}: {_safe_text(failed[-1]['error'])}", goto=None)
        problems = sum(1 for c in checks if c["status"] in {"bad", "warn"})
        try:
            self._log_change(f"Ran the health check: {problems} to look at.", kind="check")
        except OSError:
            pass
        return {"checks": checks, "problems": problems, "when": time.strftime("%Y-%m-%d %H:%M")}

    def help_packet(self):
        """One page a student can read, then choose to send to a TA. It holds nothing they typed and no personal path."""
        hw = self.tools.check_hardware()
        report = self.health()
        rt = self.runtime_state()
        mark = {"ok": "OK", "warn": "Look at this", "bad": "Problem", "optional": "Not tested"}
        log = self.changes()["changes"]
        lines = ["# Local AI Lab help report", "", f"Made {time.strftime('%Y-%m-%d %H:%M')}.",
                 "", "**Read it before you send it.** The lab doesn't send this anywhere, so sharing it is up to you.",
                 "", "## What I was trying to do", "", "(Write this part yourself. Say which step, and what you expected to happen.)", "",
                 "## This laptop", "", f"- System: {hw['os']} {hw['os_version']}, {hw.get('arch', '')}", f"- Chip: {hw['cpu_model']}",
                 f"- Memory: {hw['total_ram_gb']} GB in total, {hw['available_ram_gb']} GB free right now", f"- Free disk: {hw['free_disk_gb']} GB",
                 f"- Python {hw.get('python') or platform.python_version()}", "",
                 "## Ollama", "", "- " + ("Ollama is running." if rt["running"] else "Ollama is installed, but isn't running." if rt["installed"] else "Ollama isn't installed.")]
        if rt["lab_models"]:
            lines.append(f"- Models with their files: {', '.join(rt['lab_models'])}")
        if rt.get("broken_models"):
            lines.append(f"- Listed with no file: {', '.join(rt['broken_models'])}")
        lines += ["", "## Health check", ""]
        lines += [f"- {mark[c['status']]}: {c['label']}. {c['detail']}" for c in report["checks"]]
        with self._jobs_lock:
            failed = [j for j in self.jobs.values() if j["status"] == "failed"][-3:]
        if failed:
            lines += ["", "## Steps that failed since the helper started", ""]
            lines += [f"- {j['action']}: {_safe_text(j['error'])}" for j in failed]
        recent = [c for c in log if c.get("kind") != "assistant"][-12:]
        if recent:
            lines += ["", "## The lab's last steps", ""]
            lines += [f"- {c['when']}: {_safe_text(c['what'])}" for c in recent]
        lines += ["", "## What isn't in this report", "",
                  "Anything you typed to the assistant or to a model, any model's replies, your files, your name, and your measurements."]
        text = "\n".join(lines) + "\n"
        # A last pass over the finished page: no home folder, no account name, no secret, whatever a step's error said.
        text = _scrub(text.replace(str(Path.home()), "~"))
        return {"markdown": text, "filename": f"local-ai-lab-help-{time.strftime('%Y-%m-%d')}.md"}

    # ---------------------------------------------------------------- recipes: a reviewed list of registered steps
    def _allowed_recipe(self, recipe):
        if not isinstance(recipe, str) or recipe not in self.setups:
            raise BadRequest("Choose one of the lab's listed setups.")
        return self.setups[recipe]

    def _recipe_step_title(self, step):
        if step["action"] in {"install_app"}:
            return f"Install {APPS[step['app']]['name']}"
        if step["action"] == "pull_model":
            return f"Download {step['model']}"
        if step["action"] == "first_prompt":
            return f"Say hello to {step['model']}"
        return {"install_runtime": "Install Ollama", "start_runtime": "Start Ollama"}[step["action"]]

    def recipes(self):
        return {"recipes": [{"id": r["id"], "title": r["title"], "for": r["for"], "why": r["why"], "review": r["review"],
                             "step_titles": [self._recipe_step_title(s) for s in r["steps"]] + ["Check that everything is in place"]}
                            for r in self.setups.values()]}

    def plan_recipe(self, recipe):
        """The recipe as ordinary cards, with its total cost, before anything runs."""
        r = self._allowed_recipe(recipe)
        rt = self.runtime_state()
        compat = {m["name"]: m for m in self.compatibility()["models"]}
        steps, warnings, adds, manual_password = [], [], 0.0, False
        for i, item in enumerate(r["steps"]):
            if item["action"] == "install_app":
                ctx = app_context(item["app"])
                action = app_plan(ctx)[0]
                manual_password = manual_password or action == "install_app_manual"
            else:
                action = item["action"]
                ctx = runtime_context(self.allowed.get(item.get("model")), rt)
                manual_password = manual_password or (action == "install_runtime" and not rt["installed"])
            step = REGISTRY[action].step(ctx)
            if action == "install_app":
                step["args"] = {"app": item["app"]}
            step["id"] = f"recipe-{i}-{action}"
            steps.append(step)
            if not step["done"]:
                if "app" in item:
                    adds += APPS[item["app"]]["size_gb"]
                if action == "pull_model":
                    adds += self.allowed[item["model"]]["size_gb"]
            if "model" in item and action == "pull_model" and item["model"] in compat and compat[item["model"]]["verdict"] == "no" and not step["done"]:
                warnings.append(f"{item['model']} may not fit this laptop. {compat[item['model']]['reason']}")
            if "model" in item and action == "pull_model" and item["model"] in compat and compat[item["model"]]["verdict"] == "close_apps" and not step["done"]:
                warnings.append(f"Close some apps before you use {item['model']}. {compat[item['model']]['reason']}")
        final = REGISTRY["check_recipe"].step({"recipe": r, "name": r["title"]})
        final["id"] = "recipe-check"
        steps.append(final)
        todo = [s for s in steps if not s["done"]]
        totals = {"space": f"Adds about {round(adds, 1)} GB" if adds else "None",
                  "internet": "Yes, for the downloads" if any(s["risk"]["internet"]["value"] != "No" for s in todo) else "No",
                  "password": "The lab doesn't ask for a password. An installer you run yourself might, and its card says what to do" if manual_password else "No",
                  "money": "Free" if all(s["risk"]["money"]["value"] == "Free" for s in steps) else "See each step",
                  "steps": f"{len(todo)} to approve, one at a time"}
        return {"recipe": {k: r[k] for k in ("id", "title", "for", "why", "review")}, "steps": steps, "totals": totals, "warnings": warnings}

    def _do_check_recipe(self, job, recipe):
        """Look at the laptop itself, item by item, and name anything missing."""
        r = self._allowed_recipe(recipe)
        rt = self.runtime_state()
        log = [c.get("what", "") for c in self.changes()["changes"]]
        checks = []
        for item in r["steps"]:
            action = item["action"]
            if action == "install_app":
                name, at = APPS[item["app"]]["name"], app_path(APPS[item["app"]])
                checks.append((bool(at), f"{name} is at {at}." if at else f"{name} isn't installed."))
            elif action == "install_runtime":
                checks.append((rt["installed"], "Ollama is installed." if rt["installed"] else "Ollama isn't installed."))
            elif action == "start_runtime":
                checks.append((rt["running"], "Ollama is running." if rt["running"] else "Ollama isn't running."))
            elif action == "pull_model":
                here = item["model"] in rt["models"]
                checks.append((here, f"{item['model']} has its file on disk." if here else f"{item['model']} isn't on this laptop."))
            elif action == "first_prompt":
                said = any(line.startswith(f"Said hello to {item['model']} and it replied") for line in log)
                checks.append((said, f"{item['model']} has replied." if said else f"{item['model']} hasn't said hello yet."))
        missing = [text for ok, text in checks if not ok]
        if missing:
            raise RuntimeError(" ".join(missing))
        return {"steps": [{"ok": ok, "detail": text} for ok, text in checks]}

    # ---------------------------------------------------------------- the Use it page
    def use_info(self):
        """What the Use it page needs: the models really here, and how to come back to them without this site."""
        rt = self.runtime_state()
        cli = runtime_context(None, rt)["cli"]
        tags = rt["lab_models"]
        return {"models": [{"name": m, "about": self.allowed[m]["about"], "command": f"{cli} run {m}"} for m in tags],
                "starting_model": self._agent_model(tags),
                "launcher": "Start Lab Helper.command" if platform.system() == "Darwin" else "Start Lab Helper.bat",
                "folder": str(ROOT), "running": rt["running"], "installed": rt["installed"]}

    def start_talk(self, model, messages, context_tokens=4096, fair=False):
        """One reply from a chosen model, built up piece by piece. The conversation lives in the page and is never saved.

        fair is for side-by-side comparison: fixed settings, with nothing else in memory before or after."""
        self._allowed_model(model)
        if type(context_tokens) is not int or context_tokens not in CONTEXT_SIZES:
            raise BadRequest("Choose one of the listed context sizes.")
        if type(fair) is not bool:
            raise BadRequest("fair must be true or false.")
        if not isinstance(messages, list) or not 1 <= len(messages) <= TALK_TURNS:
            raise BadRequest("Send the conversation as a short list of messages.")
        clean = []
        for item in messages:
            if not isinstance(item, dict) or set(item) != {"role", "content"} or item["role"] not in {"user", "assistant"}:
                raise BadRequest("Each message needs only a role, user or assistant, and its content.")
            content = _text(item["content"], "message", TALK_CHARS)
            clean.append({"role": item["role"], "content": guardrails.redact_secrets(content) if item["role"] == "user" else content})
        if clean[-1]["role"] != "user":
            raise BadRequest("The conversation must end with your message.")
        if model not in self.runtime_state()["lab_models"]:
            raise BadRequest(f"{model} isn't on this laptop yet. Download it first.")
        if not self._operation_lock.acquire(blocking=False):
            raise Busy("Another lab operation is running. Wait for it to finish first.")
        talk = {"id": uuid.uuid4().hex[:12], "model": model, "status": "running", "text": "", "stop": False, "error": None, "flagged": False, "cut_off": False,
                "ttft_s": None, "tps": None, "tokens": None, "prompt_tokens": None, "load_s": None, "seconds": None, "context_tokens": context_tokens}
        with self._jobs_lock:
            while len(self.talks) >= 30:
                del self.talks[next(iter(self.talks))]
            self.talks[talk["id"]] = talk
        threading.Thread(target=self._run_talk, args=(talk, clean, fair), daemon=True).start()
        return copy.deepcopy(talk)

    def _run_talk(self, talk, messages, fair):
        client = ChatClient(self.settings.base_url, talk["model"], timeout=180)
        start = time.perf_counter()
        try:
            self.tools.ensure_model_ready(talk["model"])
            if fair:
                for other in client.loaded_models():
                    client.unload(other)
            stream = client.benchmark_stream([{"role": "system", "content": TALK_SYSTEM}, *messages], runtime=self.settings.runtime, max_tokens=TALK_TOKENS,
                                             temperature=0 if fair else 0.7, context_tokens=talk["context_tokens"])
            for ts, delta, usage in stream:
                if talk["stop"]:
                    stream.close()
                    break
                if delta:
                    if talk["ttft_s"] is None:
                        talk["ttft_s"] = round(ts - start, 2)
                    talk["text"] += delta
                if usage and usage.get("source") == "ollama_native":
                    self._read_usage(talk, usage)
            talk["seconds"] = round(time.perf_counter() - start, 2)
            talk["flagged"] = bool(guardrails.check(talk["text"]))
            talk["status"] = "stopped" if talk["stop"] else "done"
            if fair:
                client.unload(talk["model"])
        except (ValueError, RuntimeError, OSError, LLMError) as exc:
            talk.update(status="failed", error=_safe_text(exc), seconds=round(time.perf_counter() - start, 2))
        finally:
            self._operation_lock.release()
        if talk["model"] not in self._talked_with and talk["status"] in {"done", "stopped"}:
            self._talked_with.add(talk["model"])
            try:
                self._log_change(f"You talked with {talk['model']} on the Use it page. Your words aren't saved.", kind="check")
            except OSError:
                pass

    @staticmethod
    def _read_usage(talk, usage):
        count, nanos, load = usage.get("eval_count"), usage.get("eval_duration"), usage.get("load_duration")
        if type(count) is int and count >= 0:
            talk["tokens"] = count
            talk["cut_off"] = count >= TALK_TOKENS
            if type(nanos) in (int, float) and nanos > 0 and math.isfinite(nanos):
                talk["tps"] = round(count / (nanos / 1e9), 1)
        if type(usage.get("prompt_eval_count")) is int:
            talk["prompt_tokens"] = usage["prompt_eval_count"]
        if type(load) in (int, float) and load >= 0:
            talk["load_s"] = round(load / 1e9, 2)

    def talk(self, talk_id):
        with self._jobs_lock:
            if not re.fullmatch(r"[a-f0-9]{12}", talk_id) or talk_id not in self.talks:
                raise LookupError("That reply is no longer available.")
            return copy.deepcopy(self.talks[talk_id])

    def stop_talk(self, talk_id):
        with self._jobs_lock:
            if not re.fullmatch(r"[a-f0-9]{12}", talk_id) or talk_id not in self.talks:
                raise LookupError("That reply is no longer available.")
            self.talks[talk_id]["stop"] = True
        return {"ok": True}

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
        # The smallest models can't tutor well, so prefer the smallest one of 1.5B or more.
        usable = [m for m in lab_models if self.allowed[m]["params_b"] >= 1.5] or lab_models
        return min(usable, key=lambda m: self.allowed[m]["params_b"], default=None)


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


def _launch(app):
    """Fixed arguments only; `app` comes from actions.ollama_app, never from the page or the model."""
    if app.endswith(".app"):
        subprocess.run(["open", "-a", app], check=True, timeout=15)
    elif app.endswith("ollama app.exe"):
        os.startfile(app)  # type: ignore[attr-defined]  # Windows only
    else:
        subprocess.Popen([app, "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


def _reveal(path):
    """Fixed arguments only; `path` has been checked by show_model."""
    if platform.system() == "Darwin":
        subprocess.run(["open", "-R", str(path)], check=True, timeout=15)
    elif platform.system() == "Windows":
        subprocess.Popen(["explorer", f"/select,{path}"])  # explorer's exit code doesn't mean failure
    else:
        subprocess.run(["xdg-open", str(path.parent)], check=True, timeout=15)


def _folder_size(path, seconds=2.0):
    """Size of a folder in GB, giving up after a couple of seconds so a receipt never hangs."""
    deadline = time.monotonic() + seconds
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += (Path(root) / name).stat().st_size
            except OSError:
                pass
        if time.monotonic() > deadline:
            break
    return total / 1024**3


def _open_folder(path):
    """Fixed arguments only; `path` is the configured models folder, checked by show_models_folder."""
    if platform.system() == "Darwin":
        subprocess.run(["open", str(path)], check=True, timeout=15)
    elif platform.system() == "Windows":
        os.startfile(str(path))  # type: ignore[attr-defined]  # Windows only
    else:
        subprocess.run(["xdg-open", str(path)], check=True, timeout=15)


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
                return self._json(502, {"error": "The local model didn't answer. Make sure Ollama is open, then try again."})
            except Exception:
                return self._json(500, {"error": "The operation could not be completed. Check the local helper window."})

        def _route(self, method, name, b):
            if method == "GET":
                if name == "status":
                    return lab.status()
                if name == "results":
                    return lab.results()
                if name == "compatibility":
                    return lab.compatibility()
                if name == "changes":
                    return lab.changes()
                if name == "apps":
                    return lab.apps()
                if name == "receipt":
                    return lab.receipt()
                if name == "use_info":
                    return lab.use_info()
                if name == "risks":
                    return lab.risks()
                if name == "recipes":
                    return lab.recipes()
                if name == "health":
                    return lab.health()
                if name == "help_packet":
                    return lab.help_packet()
                if name.startswith("talk/"):
                    return lab.talk(name[5:])
                if name.startswith("jobs/"):
                    return lab.job(name[5:])
            else:
                if name == "recommend":
                    _body_fields(b, {"goal"}, {"goal"})
                    return lab.recommend(b["goal"])
                if name == "plan":
                    _body_fields(b, {"model"}, {"model"})
                    return lab.plan(b["model"])
                if name == "show_model":
                    _body_fields(b, {"model"}, {"model"})
                    return lab.show_model(b["model"])
                if name == "show_models_folder":
                    _body_fields(b, set())
                    return lab.show_models_folder()
                if name == "plan_recipe":
                    _body_fields(b, {"recipe"}, {"recipe"})
                    return lab.plan_recipe(b["recipe"])
                if name == "plan_app":
                    _body_fields(b, {"app"}, {"app"})
                    return lab.plan_app(b["app"])
                if name == "jobs":
                    _body_fields(b, {"action", "args"}, {"action"})
                    return lab.start_job(b["action"], b.get("args"))
                if name == "talk":
                    _body_fields(b, {"model", "messages", "context_tokens", "fair"}, {"model", "messages"})
                    return lab.start_talk(b["model"], b["messages"], b.get("context_tokens", 4096), b.get("fair", False))
                if name.startswith("talk/") and name.endswith("/stop"):
                    _body_fields(b, set())
                    return lab.stop_talk(name[5:-5])
                if name == "chat":
                    _body_fields(b, {"message", "guardrails", "open"}, {"message"})
                    if type(b.get("open", False)) is not bool:
                        raise BadRequest("open must be true or false.")
                    return lab.chat(b["message"], b.get("guardrails", True), b.get("open", False))
                if name == "chat/reset":
                    _body_fields(b, set())
                    return lab.reset_chat()
                if name == "diagnose":
                    _body_fields(b, {"text"}, {"text"})
                    return lab.diagnose(b["text"])
                if name == "try":
                    _body_fields(b, {"model", "message", "context_tokens"}, {"model", "message"})
                    return lab.try_model(b["model"], b["message"], b.get("context_tokens", 2048))
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
            file = SITE_FILES.get("/index.html" if path == "/" else path)
            if file is None:
                return self._json(404, {"error": "Not found."})
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


class LabServer(ThreadingHTTPServer):
    # One page load opens about 15 connections at once. The default queue of 5 can drop one, and a dropped app.js leaves the page dead.
    request_queue_size = 128
    daemon_threads = True


def create_server(lab, token, port=8765):
    if type(port) is not int or not 0 <= port <= 65535:
        raise ValueError("Port must be an integer from 0 to 65535.")
    if not isinstance(token, str) or not token:
        raise ValueError("A nonempty per-launch token is required.")
    for p in ([0] if port == 0 else range(port, min(port + 20, 65536))):
        try:
            return LabServer(("127.0.0.1", p), make_handler(lab, token))
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
    print("Local AI Lab helper is running on this laptop only.", flush=True)
    print("Keep this window open. Nothing changes on your laptop until you approve a step.", flush=True)
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
