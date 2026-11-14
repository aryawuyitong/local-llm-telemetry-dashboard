"""The registry of everything the lab can do to a laptop.

One Action is the single source of truth for a step: the words the learner reads
(what, why, what changes, how to undo), the command behind it, the arguments the
page may send, the Lab method that executes it, and the line written to the log.
The plan, the executor, the log and the command guardrail all read from here, so
the command shown is the command that runs, and the assistant can only ever
propose one of these. A new provider (another runtime, an app installer, a cloud
service) adds Actions here with the same fields and gets the same approval
cards, log and undo for free.
"""
from __future__ import annotations

import math
import os
import platform
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .apps import APPS, app_commands, install_command, remove_command, where_apps_go
from .config import load_allow_list

OLLAMA_DOWNLOAD = "https://ollama.com/download"
HELLO = "Say hello in three words."


# What a step costs, on every card, before it runs. Cloud actions must fill in the same six, and money most of all.
RISK_LABELS = {"time": "Time", "space": "Space", "internet": "Internet", "password": "Password", "money": "Money", "undo": "Undo"}


def _risk(time, space="None", internet="No", password="No", money="Free", undo="Nothing to undo"):
    """Each value is what the learner reads. "stop" marks a cost to look at twice; "note" one worth seeing; "none" no cost."""
    values = {"time": time, "space": space, "internet": internet, "password": password, "money": money, "undo": undo}
    levels = {"time": "note", "space": "none" if space == "None" else "note", "internet": "none" if internet == "No" else "note",
              "password": "none" if password == "No" else "stop", "money": "none" if money == "Free" else "stop",
              "undo": "stop" if undo == "No" or undo.startswith("No:") else "none"}
    return {key: {"label": RISK_LABELS[key], "value": values[key], "level": levels[key]} for key in RISK_LABELS}


def _download_time(size_gb):
    """A worked estimate, and the card says what it assumes: a 50 Mbit/s connection."""
    return f"About {max(1, math.ceil(size_gb * 8000 / 50 / 60))} minutes at 50 Mbit/s".replace("About 1 minutes", "About 1 minute")


@dataclass(frozen=True)
class Action:
    id: str
    title: Callable[[dict], str]
    args: frozenset = field(default_factory=frozenset)   # argument names the page may send
    kind: str = "action"                                  # "action" the lab runs; "manual" the learner does
    run: str | None = None                                # Lab method name; None for manual steps
    how: str = "command"                                  # "command": runs that command; "api": same effect through Ollama's local API
    describe: Callable[[dict], dict] = lambda ctx: {}     # what / why / does / undo / command / brief / link / done
    log: Callable[[dict, dict, bool], str | None] = lambda args, result, done: None  # the My lab line, or None

    def step(self, ctx: dict) -> dict:
        """The card the page shows. Every field a learner reads comes from here."""
        d = self.describe(ctx)
        if set(d.get("risk") or {}) != set(RISK_LABELS):
            raise ValueError(f"The card for {self.id} must state its time, space, internet, password, money and undo.")
        return {"id": self.id, "action": self.id if self.kind == "action" else None, "kind": self.kind,
                "title": self.title(ctx), "done": bool(d.get("done")), "what": d.get("what"), "why": d.get("why"),
                "does": d.get("does"), "undo": d.get("undo"), "command": d.get("command"), "how": self.how,
                "args": d.get("args") or {}, "link": d.get("link"), "brief": d.get("brief"), "risk": d["risk"]}


def runtime_context(model: dict | None, rt: dict) -> dict:
    """What describe() needs: the chosen model, the runtime state, and how Ollama is reached on this laptop."""
    system = platform.system()
    app = ollama_app()
    cli = "ollama"
    if system == "Darwin" and not shutil.which("ollama"):
        for bundle in (Path.home() / "Applications/Ollama.app", Path("/Applications/Ollama.app")):
            if (bundle / "Contents/Resources/ollama").is_file():
                cli = f'"{bundle}/Contents/Resources/ollama"'.replace(str(Path.home()), "$HOME")
                break
    # Start Ollama the way the executor will: the app if it is installed, else the command-line server.
    start = ("open -a Ollama" if app and app.endswith(".app") else "Start menu > Ollama" if app and app.endswith(".exe")
             else f"{cli} serve")
    return {"model": model, "name": model["ollama_tag"] if model else None, "rt": rt, "system": system,
            "cli": cli, "app": app, "start": start}


def ollama_app() -> str | None:
    if platform.system() == "Darwin":
        for path in (Path("/Applications/Ollama.app"), Path.home() / "Applications/Ollama.app"):
            if path.is_dir():
                return str(path)
    if platform.system() == "Windows":
        local_app_data = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        programs = Path(os.environ.get("ProgramFiles") or "C:/Program Files")
        for base in (local_app_data / "Programs/Ollama", programs / "Ollama"):
            exe = base / "ollama app.exe"
            if exe.is_file():
                return str(exe)
    return shutil.which("ollama")


def _install(ctx):
    return {"done": ctx["rt"]["installed"], "link": OLLAMA_DOWNLOAD,
            "what": "Ollama is the engine. It loads a model into memory and runs it.",
            "why": "A model file is only numbers. It needs a program to run it.",
            "does": ("Opens Ollama's official download page. You run the installer yourself, in your own user account. "
                     "If it offers a command-line tool and asks for your password, skip that part: the lab uses the copy inside the app. "
                     "If the installer itself asks for an admin password or your laptop blocks it, stop and ask for help. "
                     "Don't turn off Gatekeeper, antivirus or other security protections."),
            "undo": "Remove Ollama the way you'd remove any app.",
            "brief": "The runtime. Install it yourself from the official page.",
            "risk": _risk("A few minutes", "Adds one app", "Yes, from ollama.com", "The lab doesn't ask. If the installer does, see above", undo="Remove it like any app")}


def _start(ctx):
    by_app = ctx["start"] != f"{ctx['cli']} serve"
    return {"done": ctx["rt"]["running"], "command": ctx["start"],
            "what": "Ollama runs a small local server on your laptop, at port 11434.",
            "why": "This lab and the model talk through that server. It only listens on this laptop.",
            "does": "Opens the Ollama app. It installs nothing and changes no settings." if by_app
            else "Starts Ollama's server in the background. It installs nothing and changes no settings.",
            "undo": "Quit Ollama from its menu bar or system tray icon." if by_app
            else "Stop it with: ollama stop, or close the terminal window it runs in.",
            "brief": "Local server on port 11434.",
            "risk": _risk("Up to 30 seconds", undo="Quit Ollama")}


def _pull(ctx):
    m, name = ctx["model"], ctx["name"]
    gone = name in ctx["rt"].get("broken_models", [])
    return {"done": name in ctx["rt"]["models"], "args": {"model": name}, "command": f"{ctx['cli']} pull {name}",
            "what": f"This is the AI model: {m['params_b']} billion learned numbers, compressed ({m['quant']}) to about {m['size_gb']} GB.",
            "why": ("Ollama still lists this model, but its file is missing from the models folder, so it can't load. Downloading it again restores the file."
                    if gone else "Ollama is only the engine. Without a model, it has nothing to run."),
            "does": f"Adds about {m['size_gb']} GB to Ollama's models folder. Nothing else changes.",
            "undo": f"Use Undo in My lab, or run: ollama rm {name}",
            "brief": f"{m['params_b']}B, {m['quant']}, about {m['size_gb']} GB. Needs about {m['min_ram_gb']} GB of free RAM.",
            "risk": _risk(_download_time(m["size_gb"]), f"Adds about {m['size_gb']} GB", "Yes, from Ollama's model library", undo="Yes: Undo in My lab")}


def _verify(ctx):
    return {"done": False, "args": {"up_to_step": 4, "model": ctx["name"]},
            "what": "Confirms Python, Ollama, the server and the exact model are all ready.",
            "why": "If something's wrong, it's easier to fix now than after a confusing error.",
            "does": "Only reads information. Nothing changes on your laptop.",
            "brief": "Reads runtime state, model digest and disk budget. Changes nothing.",
            "risk": _risk("A few seconds")}


def _hello(ctx):
    name = ctx["name"]
    return {"done": False, "args": {"model": name}, "command": f'{ctx["cli"]} run {name} "{HELLO}"',
            "what": "Loads the model into memory and asks for a short greeting.",
            "why": "A real answer proves that every step worked.",
            "does": "Uses memory while it runs. Nothing is sent off your laptop, and the first answer can take up to 30 seconds.",
            "undo": "Nothing to undo. Ollama unloads the model from memory after a few minutes.",
            "brief": "One short prompt to prove it works.",
            "risk": _risk("Up to 30 seconds", "None, only memory while it runs")}


def _benchmark(ctx):
    name = ctx["name"]
    return {"done": False, "args": {"model": name, "repeats": 3},
            "what": "A warm-up, then three fixed prompts, each measured three times.",
            "why": "Real numbers for speed and memory, to compare with your guess.",
            "does": "Uses your processor and memory for a few minutes, then saves nine anonymous records on this laptop.",
            "undo": "Nothing changes on your laptop. Delete the results file in the lab folder if you don't want it.",
            "brief": "Three prompts, three repeats, saved locally.",
            "risk": _risk("Seconds to a few minutes", "One small results file", undo="Delete the results file")}


def _benchmark_queue(_ctx):
    return {"what": "Runs the same three prompts on each selected model, with one warm-up per model.",
            "why": "Measuring one model at a time lets us compare speed and resource use on this laptop.",
            "does": "Releases selected models from working memory before and after measurement. Model files stay on disk.",
            "undo": "Delete the local results files to remove the measurements.",
            "risk": _risk("A few minutes, depending on the models and repeats", "One small file per model", undo="Delete the results files")}


def _remove(ctx):
    name = ctx["name"]
    return {"done": False, "args": {"model": name}, "command": f"{ctx['cli']} rm {name}",
            "what": "Deletes this model's file from Ollama's models folder.",
            "why": "To free the space, or to start again.",
            "does": f"Removes {name} from this laptop. You can download it again any time.",
            "brief": "Removes the model file.",
            "risk": _risk("A few seconds", f"Frees about {ctx['model']['size_gb']} GB", undo="Download it again")}


def _hardware(ctx):
    return {"done": False, "command": "system_profiler SPHardwareDataType" if ctx["system"] == "Darwin" else "systeminfo",
            "what": "Reads your system, chip, memory and free disk space.",
            "why": "To suggest a model that fits, the lab needs to know what this laptop has.",
            "does": "Reads system information. Changes nothing, and nothing leaves your laptop.",
            "brief": "Read only.",
            "risk": _risk("A few seconds")}


# ---------------------------------------------------------------- second provider: apps
def _install_app(ctx):
    app, m = ctx["app"], ctx["manager"]
    return {"done": bool(ctx["installed_at"]), "args": {"app": app["id"]}, "command": install_command(ctx), "link": app["site"],
            "what": app["what"], "why": app["why"],
            "does": (f"{m['name']} downloads {app['name']} from its publisher and puts it in {where_apps_go(ctx)}, about {app['size_gb']} GB. "
                     f"It keeps a copy of the download in its own cache. Nothing else changes, and it never needs your password."
                     + (" The two --accept flags agree to the publisher's licence for you, the same as clicking Agree in an installer." if ctx["system"] == "Windows" else "")),
            "undo": f"Use Undo in My lab, or run: {remove_command(ctx)}",
            "brief": f"About {app['size_gb']} GB, via {m['name']}.",
            "risk": _risk(_download_time(app["size_gb"]), f"Adds about {app['size_gb']} GB", f"Yes, through {m['name']}", undo="Yes: Undo in My lab")}


def _install_app_manual(ctx):
    app, m = ctx["app"], ctx["manager"]
    return {"done": bool(ctx["installed_at"]), "link": app["site"],
            "what": app["what"], "why": app["why"],
            "does": (f"Opens {app['name']}'s official download page. You run the installer yourself, in your own user account. "
                     f"This laptop has no {m['name']}, which is how the lab would otherwise install it. "
                     "If the installer asks for an admin password, stop and ask for help."),
            "undo": f"Remove {app['name']} the way you'd remove any app.",
            "brief": f"About {app['size_gb']} GB. Install it yourself from the official page.",
            "risk": _risk("A few minutes", f"Adds about {app['size_gb']} GB", "Yes, from the publisher", "The lab doesn't ask. If the installer does, stop", undo="Remove it like any app")}


def _check_app(ctx):
    return {"done": False, "args": {"app": ctx["app"]["id"]},
            "what": f"Confirms {ctx['app']['name']} is really in {where_apps_go(ctx)}.",
            "why": "An installer can finish without the app being where it should be.",
            "does": "Only reads information. Nothing changes on your laptop.",
            "brief": "Checks the app's folder. Changes nothing.",
            "risk": _risk("A few seconds")}


def _remove_app(ctx):
    app = ctx["app"]
    return {"done": False, "args": {"app": app["id"]}, "command": remove_command(ctx),
            "what": f"Removes {app['name']} from {where_apps_go(ctx)}.",
            "why": "To put the laptop back the way it was.",
            "does": f"Removes {app['name']}. Your files and settings for it stay, and you can install it again any time.",
            "brief": "Removes the app.",
            "risk": _risk("Up to a minute", f"Frees about {app['size_gb']} GB", undo="Install it again")}


# ---------------------------------------------------------------- recipes: one check at the end of a reviewed list
def _check_recipe(ctx):
    return {"done": False, "args": {"recipe": ctx["recipe"]["id"]},
            "what": f"Confirms that everything in {ctx['recipe']['title']} is really in place.",
            "why": "A list of finished steps isn't proof. This looks at the laptop itself.",
            "does": "Only reads information. Nothing changes on your laptop.",
            "brief": "Looks at the laptop. Changes nothing.",
            "risk": _risk("A few seconds")}


REGISTRY: dict[str, Action] = {a.id: a for a in [
    Action("check_hardware", lambda c: "Let the assistant read your laptop's specs", run="_do_check_hardware", describe=_hardware,
           log=lambda a, r, done: "Checked your laptop."),
    Action("install_runtime", lambda c: "Install Ollama, the program that runs models", kind="manual", describe=_install),
    Action("start_runtime", lambda c: "Start Ollama", run="_do_start_runtime", describe=_start),
    Action("pull_model", lambda c: f"Download {c['name']}", args=frozenset({"model"}), run="_do_pull_model", how="api", describe=_pull),
    Action("check_install", lambda c: "Check that everything is in place", args=frozenset({"up_to_step", "model"}),
           run="_do_check_install", describe=_verify, log=lambda a, r, done: "Checked that everything is in place."),
    Action("first_prompt", lambda c: f"Say hello to {c['name']}", args=frozenset({"model"}), run="_do_first_prompt", how="api", describe=_hello,
           log=lambda a, r, done: f"Said hello to {a.get('model')}" + (f" and it replied in {r.get('seconds')} s." if done else ".")),
    Action("benchmark", lambda c: f"Measure {c['name']}", args=frozenset({"model", "repeats", "guess_tps", "guess_ram_gb"}),
           run="_do_benchmark", how="api", describe=_benchmark,
           log=lambda a, r, done: f"Measured {a.get('model')}" + (f": {r.get('median_tps')} tokens/s, peak {round(r.get('peak_ram_mb') or 0)} MiB." if done else ".")),
    Action("benchmark_queue", lambda c: "Measure selected models", args=frozenset({"models", "repeats", "guess_tps", "guess_ram_gb"}),
           run="_do_benchmark_queue", how="api", describe=_benchmark_queue,
           log=lambda a, r, done: "Measured a queue of selected models."),
    Action("remove_model", lambda c: f"Remove {c['name']}", args=frozenset({"model"}), run="_do_remove_model", how="api", describe=_remove),
    # The second provider. Same card, log and undo; the command shown is the command run.
    Action("install_app", lambda c: f"Install {c['name']}", args=frozenset({"app"}), run="_do_install_app", describe=_install_app),
    Action("install_app_manual", lambda c: f"Install {c['name']}", kind="manual", describe=_install_app_manual),
    Action("check_app", lambda c: f"Check that {c['name']} is in place", args=frozenset({"app"}), run="_do_check_app", describe=_check_app,
           log=lambda a, r, done: f"Checked that {APPS.get(a.get('app'), {}).get('name', a.get('app'))} is in place."),
    Action("remove_app", lambda c: f"Remove {c['name']}", args=frozenset({"app"}), run="_do_remove_app", describe=_remove_app),
    Action("check_recipe", lambda c: "Check that everything is in place", args=frozenset({"recipe"}), run="_do_check_recipe", describe=_check_recipe,
           log=lambda a, r, done: f"Checked the {a.get('recipe')} setup." ),
]}

# The order of the setup plan for one model. verify_install is check_install under its page name.
PLAN = ("install_runtime", "start_runtime", "pull_model", "check_install", "first_prompt")
PAGE_IDS = {"check_install": "verify_install"}
APP_ACTIONS = frozenset({"install_app", "install_app_manual", "check_app", "remove_app"})


def app_plan(ctx: dict) -> tuple[str, ...]:
    """Install through the package manager when the laptop has one; otherwise it is a manual step from the official page."""
    return ("install_app" if ctx["manager"]["installed"] else "install_app_manual", "check_app")

# Lab commands the assistant may also show that aren't a step: read-only checks and the documented setup.
EXTRA_COMMANDS = (
    "ollama list", "ollama ps", "ollama --version", "ollama -v", "ollama stop", "python3 --version", "python --version",
    "py -3 --version", "lsof -i :11434", "system_profiler SPHardwareDataType", "systeminfo",
    "python3 -m venv .venv", "py -3 -m venv .venv", ".venv/bin/python -m pip install -r requirements.txt",
    ".venv\\Scripts\\python.exe -m pip install -r requirements.txt", ".venv/bin/python -m telemetry_agent.helper",
    ".venv\\Scripts\\python.exe -m telemetry_agent.helper", "python3 -m pip install --user psutil",
    "cd agent", "cd local-llm-telemetry-dashboard/agent",
)


# Read-only checks whose last argument varies (a file, a URL): allowed by prefix, never anything that changes a laptop.
READ_ONLY_PREFIXES = ("xattr -p com.apple.quarantine ", "curl -I https://", "ollama show ")


def registered_commands() -> set[str]:
    """Every exact command this lab teaches, for the allow-listed models, on any OS. Anything else is not ours."""
    found = set(EXTRA_COMMANDS)
    for tag in [m["ollama_tag"] for m in load_allow_list()]:
        for cli in ("ollama", "$HOME/Applications/Ollama.app/Contents/Resources/ollama"):
            found |= {f"{cli} pull {tag}", f"{cli} rm {tag}", f'{cli} run {tag} "{HELLO}"', f"{cli} run {tag}", f"{cli} stop {tag}"}
    found |= {"open -a Ollama", "ollama serve"}
    return found | app_commands()
