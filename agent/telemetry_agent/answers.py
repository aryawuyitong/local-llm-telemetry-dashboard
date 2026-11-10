"""Answers written by code from real checks, for the questions a new student really asks.

A small local model invents facts: on a real laptop it named a model called "any", gave a wrong
folder and said yes to homework use. So anything about this laptop, or anything the lab has a
reviewed answer to, is answered here. The model only sees the open questions that are left.

answer() returns None when the question is open. Otherwise it returns:
  id         which answer, for the log (never the learner's words)
  kind       "checked": read from this laptop just now; "notes": the lab's reviewed text
  text       the reply, in the small Markdown the page renders
  checked    what was read to write it, shown under the reply
  proposals  (action, args) pairs that become the usual approval cards
  links      {"label", "goto"} buttons to a page of the site
"""
from __future__ import annotations

import platform
import re
import time

from .actions import _download_time, app_plan, runtime_context
from .agent import _app_for, _step_for
from .apps import APPS, app_context, app_path
from .config import ROOT
from .llm import ChatClient, LLMError


def _reply(id_, kind, text, checked=(), proposals=(), links=()):
    return {"id": id_, "kind": kind, "text": text.strip(), "checked": list(checked), "proposals": list(proposals), "links": list(links)}


def _link(label, goto):
    return {"label": label, "goto": goto}


def _names(tags):
    return ", ".join(f"`{t}`" for t in tags)


def _when(iso):
    return str(iso or "")[:10]


def _mentioned(lab, text):
    return next((m for m in sorted(lab.allowed, key=len, reverse=True)
                 if re.search(rf"(?<![\w.:]){re.escape(m)}(?![\w.:])", text, re.I)), None)


def _smallest(lab, tags):
    return min(tags, key=lambda m: lab.allowed[m]["params_b"])


def _measurements(lab):
    """The newest session for each model. Sessions arrive newest first."""
    seen = {}
    for row in lab.results()["models"]:
        if row.get("median_tps") is not None:
            seen.setdefault(row["model"], row)
    return seen


def _measure_line(tag, row):
    speed = f"{round(row['median_tps'])} tokens per second"
    first = f", first word after {round(row['median_ttft_ms'])} ms" if row.get("median_ttft_ms") is not None else ""
    memory = f", peak memory {row['peak_ram_mb'] / 1024:.1f} GiB" if row.get("peak_ram_mb") is not None else ""
    return f"- `{tag}`: {speed}{first}{memory}. Measured {_when(row.get('last_run'))}."


def _last_hello(lab):
    for row in reversed(lab.changes()["changes"]):
        found = re.fullmatch(r"Said hello to (\S+) and it replied in ([\d.]+) s\.", row.get("what", ""))
        if found:
            return found.group(1), found.group(2), row.get("when")
    return None


def _how_ollama_starts(rt):
    return "Open the Ollama app. On a Mac it's in Applications; on Windows it's in the Start menu." if rt["installed"] else ""


# ---------------------------------------------------------------- answers that read this laptop
def status(lab):
    rt = lab.runtime_state()
    read = ["Ollama's server", "the model files on disk"]
    if not rt["installed"]:
        return _reply("status", "checked", "Not yet. Ollama isn't installed on this laptop, and it's the engine that runs a model.\n\n"
                      "Next step: install it from its official page. Set up walks you through it.",
                      read, links=[_link("Go to Set up", "deploy")])
    if not rt["running"]:
        return _reply("status", "checked", "Not right now. Ollama is installed, but it isn't running. "
                      "Approve the card below and the lab will start it.", read, [("start_runtime", {})])
    if not rt["lab_models"]:
        gone = f" Ollama still lists {_names(rt['broken_models'])}, but the file is gone." if rt.get("broken_models") else ""
        pick, _ = lab._goal_pick("try")
        proposals = [("pull_model", {"model": pick["name"]})] if pick else []
        return _reply("status", "checked", f"Almost. Ollama is running, but no model is on this laptop yet.{gone}\n\n"
                      + ("Next step: download one. This card has a suggestion that fits your memory." if pick else "Next step: pick one on the Catalog page."),
                      read, proposals, [_link("See the models", "catalog")])
    lines = [f"Ollama is running, and these models have their files on disk: {_names(rt['lab_models'])}."]
    if rt.get("broken_models"):
        lines.append(f"These are listed without a file, so they can't run: {_names(rt['broken_models'])}.")
    hello = _last_hello(lab)
    if hello:
        lines.append(f"The last reply I can see came from `{hello[0]}` on {hello[2]}, in {hello[1]} seconds.")
    model = _smallest(lab, rt["lab_models"])
    lines.append("Having the file doesn't prove it answers. This card asks it for a short greeting, which does.")
    return _reply("status", "checked", "\n\n".join(lines), read + ["the lab's log"], [("first_prompt", {"model": model})],
                  [_link("Use it", "use")])


def where_models(lab):
    rt = lab.runtime_state()
    lines = [f"Ollama keeps every model in one folder on this laptop:\n`{rt['models_dir']}`"]
    if not rt.get("models_dir_exists"):
        lines.append("That folder doesn't exist yet. It appears after your first download.")
    if rt["models"]:
        lines.append(f"Their files are on disk: {_names(rt['models'])}.")
    if rt.get("broken_models"):
        lines.append(f"Listed, but the file is gone: {_names(rt['broken_models'])}.")
    lines.append("Inside, the files are named by a code, not the model's name, so don't move or rename them. "
                 "My lab has an Open folder button, and it can show you each model's own file.")
    return _reply("where_models", "checked", "\n\n".join(lines), ["Ollama's settings", "the model files on disk"], links=[_link("Open My lab", "mylab")])


def my_models(lab):
    rt = lab.runtime_state()
    if not rt["running"] and not rt["installed"]:
        return _reply("my_models", "checked", "Nothing is on this laptop yet. Set up starts with Ollama, then one model.", ["Ollama's server"], links=[_link("Go to Set up", "deploy")])
    if not rt["running"]:
        return _reply("my_models", "checked", "I can't tell right now, because Ollama isn't running. Approve this card to start it, then ask again.", ["Ollama's server"], [("start_runtime", {})])
    lines = []
    if rt["lab_models"]:
        sizes = [f"- `{m}`: about {lab.allowed[m]['size_gb']} GB" for m in rt["lab_models"]]
        lines.append(f"{len(rt['lab_models'])} on this laptop:\n" + "\n".join(sizes))
    else:
        lines.append("No model has its file on this laptop yet.")
    if rt.get("broken_models"):
        lines.append(f"Listed by Ollama with no file, so they can't run: {_names(rt['broken_models'])}.")
    return _reply("my_models", "checked", "\n\n".join(lines), ["Ollama's list", "the model files on disk"], links=[_link("Open My lab", "mylab")])


def fit(lab):
    compat = lab.compatibility()
    groups = {"yes": [], "close_apps": [], "no": []}
    for row in compat["models"]:
        groups[row["verdict"]].append(row["name"])
    lines = [f"This laptop has {compat['total_ram_gb']} GB of memory, with {compat['free_ram_gb']} GB free right now."]
    if groups["yes"]:
        lines.append(f"Ready now: {_names(groups['yes'])}.")
    if groups["close_apps"]:
        lines.append(f"Close some apps first: {_names(groups['close_apps'])}.")
    if groups["no"]:
        lines.append(f"Won't fit right now: {_names(groups['no'])}.")
    pick, _ = lab._goal_pick("try")
    proposals = []
    if pick:
        lines.append(f"I'd start with `{pick['name']}`, because it's small and has no separate license to read.")
        if pick["name"] not in lab.runtime_state()["models"]:
            proposals.append(("pull_model", {"model": pick["name"]}))
    lines.append("These needs are planning estimates, so your real numbers will differ.")
    return _reply("fit", "checked", "\n\n".join(lines), ["this laptop's memory and disk", "the lab's model list"], proposals, [_link("See every model", "catalog")])


def model_facts(lab, tag):
    m = lab.allowed[tag]
    row = next(r for r in lab.compatibility()["models"] if r["name"] == tag)
    verdict = {"yes": "It should fit right now.", "close_apps": "It should fit if you close some apps.", "no": "It won't fit right now."}[row["verdict"]]
    lines = [f"`{tag}`: {m['about']}",
             f"It's about {m['size_gb']} GB to download and needs about {m['min_ram_gb']} GB of free memory. Those are planning estimates.",
             f"{verdict} {row['reason']}"]
    if row["installed"]:
        lines.append("It's already on this laptop.")
    elif row["missing_file"]:
        lines.append("Ollama lists it, but its file is gone, so it needs downloading again.")
    run = _measurements(lab).get(tag)
    if run:
        lines.append("You measured it:\n" + _measure_line(tag, run))
    proposals = [("pull_model", {"model": tag})] if not row["installed"] and row["verdict"] != "no" else []
    return _reply("model_facts", "checked", "\n\n".join(lines), ["this laptop's memory and disk", "the lab's model list"], proposals)


def measurements(lab):
    runs = _measurements(lab)
    rt = lab.runtime_state()
    if not runs:
        proposals = [("benchmark", {"model": _smallest(lab, rt["lab_models"]), "repeats": 3})] if rt["lab_models"] else []
        return _reply("measurements", "checked", "You haven't measured anything on this laptop yet."
                      + (" This card measures your smallest model." if proposals else " Download a model first."),
                      ["your saved results"], proposals, [_link("Open Measure", "measure")])
    lines = "\n".join(_measure_line(tag, row) for tag, row in runs.items())
    return _reply("measurements", "checked", f"Your latest measurements on this laptop:\n\n{lines}\n\nA faster reply says nothing about whether the answer is good. "
                  "Use it has a side-by-side comparison for that.", ["your saved results"], links=[_link("See the charts", "measure")])


def changed(lab):
    entries = [c for c in lab.changes()["changes"] if c.get("kind", "change") == "change" and not c.get("undone")]
    lines = []
    if entries:
        lines.append("What the lab changed, and hasn't undone:\n" + "\n".join(f"- {c['what']} ({c['when']})" for c in entries[-8:]))
    else:
        lines.append("The lab's log shows nothing it changed and hasn't undone.")
    lines.append("To take something back, click Undo on it in My lab. The receipt there lists everything else the lab added, with its size and how to remove it.")
    return _reply("changed", "checked", "\n\n".join(lines), ["the lab's log"], links=[_link("Open My lab", "mylab")])


def hardware(lab):
    hw = lab.tools.check_hardware()
    text = (f"{hw['os']} {hw['os_version']}, {hw['cpu_model']}.\n\n"
            f"- Memory: {hw['total_ram_gb']} GB in total, {hw['available_ram_gb']} GB free right now\n"
            f"- Free disk: {hw['free_disk_gb']} GB\n- Graphics: {hw['gpu']}\n- Python: {hw['python']}")
    return _reply("hardware", "checked", text, ["this laptop's system information"], links=[_link("Which models fit?", "catalog")])


def reopen(lab):
    rt = lab.runtime_state()
    if not rt["installed"]:
        return _reply("reopen", "checked", "There's nothing to reopen yet. Install Ollama first, using Set up.", ["Ollama's server"], links=[_link("Go to Set up", "deploy")])
    launcher = "Start Lab Helper.command" if platform.system() == "Darwin" else "Start Lab Helper.bat"
    cli = runtime_context(None, rt)["cli"]
    lines = ["Your models stay on this laptop, so nothing needs downloading again. Two things stop when you close them, and you restart them like this:",
             f"1. {_how_ollama_starts(rt)}\n2. Double-click **{launcher}** in this folder: `{ROOT}`. It opens this site with a new private link."]
    if rt["lab_models"]:
        lines.append(f"You can also talk to a model without the lab. Once Ollama is open, type this in a terminal:\n\n```\n{cli} run {_smallest(lab, rt['lab_models'])}\n```")
    return _reply("reopen", "checked", "\n\n".join(lines), ["Ollama's server", "the lab's folder"], links=[_link("Use it", "use")])


HEALTH = _reply("health", "notes", "My lab has a health check. It re-runs every check on this laptop, changes nothing, and offers a repair card for whatever it can repair.\n\n"
                "It can also make a one-page help report for your TA. You read that first, and sharing it is up to you.", links=[_link("Open My lab", "mylab")])


def download_time(lab):
    rt = lab.runtime_state()
    rows = [m for m in sorted(lab.allowed.values(), key=lambda m: m["params_b"]) if not m["license_gate"]][:3]
    lines = "\n".join(f"- `{m['ollama_tag']}`, about {m['size_gb']} GB: {_download_time(m['size_gb'])}" + (" (already here)" if m["ollama_tag"] in rt["models"] else "") for m in rows)
    return _reply("download_time", "checked", f"It depends on your connection. These are worked out from each model's size, and they're only estimates:\n\n{lines}\n\n"
                  "Every download card shows its own estimate before you approve it.", ["the lab's model list", "the model files on disk"], links=[_link("See every model", "catalog")])


def stop_model(lab):
    return _reply("stop_model", "notes", "You don't need to do anything. Ollama frees a model from memory by itself a few minutes after its last reply, and the file stays on disk.\n\n"
                  "To stop everything now, quit Ollama from its menu bar or system tray icon. To stop a reply on the Use it page, press Stop.", links=[_link("Use it", "use")])


def setups(lab):
    listed = "\n".join(f"- **{r['title']}**: {r['for']}." for r in lab.setups.values())
    return _reply("recipes", "notes", f"The Catalog page has ready-made setups. Each one is a list of the lab's usual steps, ending in one check, and you still approve every step:\n\n{listed}\n\n"
                  "None of them replaces your course's own setup page, so read that first.", links=[_link("See the setups", "catalog")])


def slow(lab):
    hw = lab.tools.check_hardware()
    rt = lab.runtime_state()
    lines = [f"Right now this laptop has {hw['available_ram_gb']} GB of memory free, out of {hw['total_ram_gb']} GB."]
    tight = [m for m in rt["lab_models"] if lab.allowed[m]["min_ram_gb"] > hw["available_ram_gb"]]
    if tight:
        lines.append(f"That's less than these models want: {_names(tight)}. Closing big apps should help.")
    runs = _measurements(lab)
    if runs:
        lines.append("Your measured speeds, to compare against:\n" + "\n".join(_measure_line(t, r) for t, r in runs.items()))
    lines.append("The first reply after loading is also always slower. If it stays slow, try a smaller model.")
    return _reply("slow", "checked", "\n\n".join(lines), ["this laptop's free memory", "your saved results"], links=[_link("Measure it", "measure")])


def last_problem(lab):
    with lab._jobs_lock:
        failed = [j for j in lab.jobs.values() if j["status"] == "failed"]
    if not failed:
        return _reply("last_problem", "checked", "No step has failed since the Lab Helper started. If you saw an error somewhere else, paste it here.", ["the steps run so far"])
    job = failed[-1]
    lines = [f"The last step to fail was `{job['action']}`. It said:\n\n```\n{job['error']}\n```"]
    if job.get("diagnosis"):
        d = job["diagnosis"]
        lines.append(f"**{d['title']}.** {d['cause']}\n\n" + "\n".join(f"{i}. {f}" for i, f in enumerate(d["fix"] if isinstance(d["fix"], list) else [d["fix"]], 1)))
    else:
        lines.append("That isn't on the list of known errors, so I won't guess at a fix. My lab can make a help report for your TA.")
    return _reply("last_problem", "checked", "\n\n".join(lines), ["the steps run so far"], links=[_link("Open My lab", "mylab")])


def known_error(lab, match):
    lines = [f"**{match['title']}.** {match['cause']}", "\n".join(f"{i}. {f}" for i, f in enumerate(match["fix"] if isinstance(match["fix"], list) else [match["fix"]], 1))]
    if match.get("id") == "server_not_running" and lab.runtime_state()["running"]:
        lines.append("Ollama is running on this laptop right now, so try that step again first.")
    if match.get("learn"):
        lines.append(f"Why it matters: {match['learn']}")
    return _reply("known_error", "notes", "\n\n".join(lines), ["the lab's list of known errors"])


# ---------------------------------------------------------------- cards
def _ask_for_model(lab, tag, step):
    rt = lab.runtime_state()
    here = tag in rt["models"]
    if step == "pull_model":
        if here:
            return _reply("step", "checked", f"`{tag}` is already on this laptop, so there's nothing to download.", ["the model files on disk"], links=[_link("Use it", "use")])
        return _reply("step", "checked", f"Here's the step for `{tag}`. Nothing happens until you approve it.", ["the model files on disk"], [("pull_model", {"model": tag})])
    if not here:
        return _reply("step", "checked", f"`{tag}` isn't on this laptop yet, so download it first. Here's that step.", ["the model files on disk"], [("pull_model", {"model": tag})])
    args = {"model": tag, "repeats": 3} if step == "benchmark" else {"model": tag}
    return _reply("step", "checked", f"Here's the step for `{tag}`. Nothing happens until you approve it.", ["the model files on disk"], [(step, args)])


def _ask_for_app(lab, app, step):
    ctx = app_context(app)
    name = APPS[app]["name"]
    at = app_path(APPS[app])
    if step == "remove_model":
        return _reply("step", "checked", f"Here's the step that removes {name}. Nothing happens until you approve it. The lab only removes apps it installed.", ["the Applications folder"], [("remove_app", {"app": app})])
    if at:
        return _reply("step", "checked", f"{name} is already installed at `{at}`.", ["the Applications folder"], links=[_link("See the apps", "catalog")])
    action = app_plan(ctx)[0]
    if action == "install_app":
        return _reply("step", "checked", f"Here's the step that installs {name}. Nothing happens until you approve it.", ["the Applications folder", "this laptop's installer"], [("install_app", {"app": app})])
    return _reply("step", "checked", f"This laptop has no {ctx['manager']['name']}, so {name} is a manual install from its official page. The Catalog page has the link.",
                  ["this laptop's installer"], links=[_link("See the apps", "catalog")])


def _other_app(name):
    apps = " and ".join(a["name"] for a in APPS.values())
    return _reply("step", "notes", f"I can't install {name}. The lab only installs {apps}, because each one has a reviewed card with an exact command and an undo. "
                  "Use its official page for anything else.", links=[_link("See the apps", "catalog")])


def _ask_for_step(lab, text, step):
    tag = _mentioned(lab, text)
    if tag:
        return _ask_for_model(lab, tag, step)
    rt = lab.runtime_state()
    if step == "start_runtime":
        return (_reply("step", "checked", "Ollama is already running.", ["Ollama's server"]) if rt["running"] else
                _reply("step", "checked", "Here's the step that starts Ollama. Nothing happens until you approve it.", ["Ollama's server"], [("start_runtime", {})]))
    if step == "pull_model":
        return fit(lab)
    if not rt["lab_models"]:
        return status(lab)
    model = _smallest(lab, rt["lab_models"])
    note = "" if len(rt["lab_models"]) == 1 else f" You also have {_names([m for m in rt['lab_models'] if m != model])}: name one to use it instead."
    if step == "remove_model":
        return _reply("step", "checked", f"Which one? On this laptop: {_names(rt['lab_models'])}. Say `remove` and the name, or use Undo in My lab.", ["the model files on disk"], links=[_link("Open My lab", "mylab")])
    args = {"model": model, "repeats": 3} if step == "benchmark" else {"model": model}
    return _reply("step", "checked", f"Here's the step for `{model}`.{note} Nothing happens until you approve it.", ["the model files on disk"], [(step, args)])


# ---------------------------------------------------------------- answers the lab has reviewed
COURSE_RULES = _reply("course_rules", "notes",
                      "I can't tell you that, because each course sets its own AI rules and I can't see them. Check the syllabus or ask your instructor before you use this for anything graded.\n\n"
                      "Running a model on your own laptop doesn't change those rules. If AI is allowed, say that you used it, in the way the course asks.\n\n"
                      "And check its answers yourself. Small models often get facts wrong and still sound sure.")

PRIVACY = _reply("privacy", "notes",
                 "Your questions stay on this laptop. The lab listens only to this laptop, and the model runs here through Ollama. No account is needed, and there's no analytics.\n\n"
                 "You need internet for downloads: the lab, Ollama, and each model. After that a model works offline.\n\n"
                 "Results files stay here unless you share them yourself, so look inside one before you send it to anyone.",
                 links=[_link("What runs where", "learn")])

GOOD_FOR = _reply("good_for", "notes",
                  "A small local model is good for private first drafts, rewriting text, explaining ideas in simple terms, and small code questions. It works offline and costs nothing per question.\n\n"
                  "It's weaker than a big cloud model such as ChatGPT, because your laptop's memory limits its size. It can invent facts, dates and references, and it often gets arithmetic wrong. "
                  "It can't browse the web, read your files, or learn about recent events, and it only remembers the current conversation.\n\n"
                  "So use it where you can check the answer. Use it has starter prompts, and a way to compare two models side by side.",
                  links=[_link("Use it", "use")])

WHAT_YOU_DO = _reply("what_you_do", "notes",
                     "I can tell you what's on this laptop, whether setup is finished, where your models are, which models fit, what you've measured, and what the lab has changed. Those answers come from real checks, not from an AI model.\n\n"
                     "I can also set up a step for you to approve, such as a download, and explain known errors. Other questions go to the model on this laptop, which can be wrong.")

UNKNOWN_ERROR = _reply("unknown_error", "notes",
                       "That isn't on the lab's list of known errors, so I won't guess at a fix. If you can, paste the exact words of the error here.\n\n"
                       "Don't turn off any security setting to get past it. My lab's health check may show what's wrong, and it can make a one-page report for your TA.",
                       links=[_link("Open My lab", "mylab")])

ERROR_WORDS = re.compile(
    r"\berror\b|\bfailed\b|traceback|exception|not found|permission denied|access denied|refused|not recognized|no such file|errno|"
    r"already in use|out of memory|no space left|(?:cannot|can't|couldn't) (?:connect|open|find|load|start|access)", re.I)

GLOSSARY = [
    (r"tokens? per second|\btps\b|tok/s|tokens/s", "**Tokens per second** is how fast the words appear once the model gets going. Tokens are pieces of words. It says nothing about whether the answer is any good."),
    (r"\btokens?\b", "A **token** is a piece of a word. \"understanding\" might be two or three tokens. Models read and write tokens, one at a time."),
    (r"quanti[sz]\w*|q4_k_m|\bq4\b", "**Quantization** stores each of a model's numbers more roughly, so the file is smaller and fits in less memory, at a small cost in quality. Q4_K_M in a model's name is one way of doing it."),
    (r"\bparameters?\b|\bweights?\b|\b\d(\.\d)?b\b", "**Parameters** are the model's learned numbers. \"1.5B\" means about 1.5 billion of them. More usually means better answers, and more memory."),
    (r"\bcontext\b", "The **context** is everything the model is holding in mind right now: your messages plus its replies so far. A longer context needs more memory, and once it's full the oldest part is forgotten."),
    (r"\bollama\b|\bruntime\b", "**Ollama** is the engine that runs models. A model file can't do anything by itself, so Ollama loads it and turns your question into a reply. It stays on your laptop."),
    (r"local (vs\.?|versus|and|or) cloud|cloud (vs\.?|versus|and|or) local|\bcloud ai\b|\blocal ai\b", "A cloud service such as ChatGPT runs on someone else's computers, and your words travel there and back. A **local** model runs on your own laptop, so your words stay here and it works offline. The trade-off: your memory limits its size, so local models are usually smaller and make more mistakes."),
    (r"\bttft\b|first (word|token|response)|latency", "The **wait for the first word** is the pause before anything appears, while the model reads your message. The first reply after loading takes longer, because the model has to load too."),
    (r"\bram\b|\bmemory\b", "**Memory**, or RAM, is where a model has to fit before it can run at all, so free memory decides what you can use. It's different from disk space, which is where the file is kept."),
    (r"\bgpu\b|\bcpu\b|graphics chip|processor", "The **CPU** is the main processor. The **GPU**, or graphics chip, is often faster at this kind of work, and Ollama uses it when it can. That's why the CPU can look idle while replies come quickly."),
    (r"\bmedian\b|middle result", "The **median** is the middle result when runs are put in order. The lab uses it because one odd run can't move it much."),
    (r"\bgguf\b", "**GGUF** is a file format that holds a model's numbers and settings in one file. You don't need to handle it directly, because Ollama manages its own files."),
    (r"\b(llm|large language model|language model|a model|the model|ai model)\b", "A **model** is a file of learned numbers. Given your words, it works out which token is likely to come next, adds it, and repeats. It predicts text and doesn't look up facts, which is why it can sound sure and still be wrong."),
]
DEFINE = re.compile(r"^\s*(what('?s| is| are| does| do)\b|define\b|explain\b|meaning of\b|tell me what\b|difference between\b)", re.I)
NOT_DEFINE = re.compile(r"\b(my|mine|this laptop|i|me)\b", re.I)
LAB_TERM_HINT = re.compile(r"\b(class|function|loop|variable|photosynth\w*|derivative|recursion)\b", re.I)


def glossary(text):
    if not DEFINE.search(text) or NOT_DEFINE.search(text) or LAB_TERM_HINT.search(text):
        return None
    for pattern, body in GLOSSARY:
        if re.search(pattern, text, re.I):
            return _reply("glossary", "notes", body, links=[_link("More on Learn", "learn")])
    return None


# ---------------------------------------------------------------- which question is this?
COURSE_FOUND_OUT = re.compile(r"\b(professor|instructor|ta|teacher)\b.*\b(know|find out|detect|tell|catch)\b", re.I)
COURSE_WORDS = re.compile(r"\b(homework|assignments?|course ?work|exams?|midterms?|essays?|thesis|dissertation|syllabus|graded|cmu)\b|academic integrity|(?:for|in|on) (?:my |a |this )?(?:class|course)\b|\b(?:cheat\w*|plagiari\w*)\b", re.I)
COURSE_ASK = re.compile(r"\b(can|may|could|should) i\b|\bam i allowed\b|\ballowed\b|\bis (it|this|that) (ok|okay|fine|cheating)\b|\bcheat\w*|\bplagiari\w*|\bpolicy\b|\brules?\b", re.I)
PATTERNS = [
    ("health", re.compile(r"^\s*help[\s!.?]*$|\b(get|need) (some )?help\b|\bhealth ?check\b|\bcheck (everything|my laptop|the lab)\b|\b(fix|repair) (it|this|everything|my (setup|install|lab))\b|\bhelp (report|packet)\b|\b(tell|ask|email|message) (my |the )?(ta|instructor|professor)\b|\bwhat (do|should) i (send|tell)\b", re.I)),
    ("recipes", re.compile(r"\brecipes?\b|ready-made|\bset ?up (my|this|the) (laptop|computer|mac|pc) for\b|\bset (this|it) up for\b|\bset ?ups? (do you|are there|can)\b", re.I)),
    ("last_problem", re.compile(r"what went wrong|why did (it|that|this) (fail|break|stop)|what was (the|that) error|\blast error\b", re.I)),
    ("reopen", re.compile(r"\bcome back\b|\bget back (in|to)\b|\b(open|start|launch|get|come|use|run|restart|reopen|back|talk|chat)\b.*\b(again|tomorrow|later|next time)\b|\bclosed? (my|the) (laptop|lid|window|tab|terminal)\b|"
                          r"\b(restarted|rebooted|shut down|turned off) (my|the) (laptop|computer|mac|pc)\b|\breopen\b|"
                          r"\b(use|run|talk|chat)\b.*\b(terminal|command line)\b|\b(terminal|command line)\b.*\b(use|run|talk|chat)\b|without (the |this )?(lab|helper|website|site)\b", re.I)),
    ("privacy", re.compile(r"\b(send|sends|sent|upload|uploads|leave|leaves|share|shares|go|goes)\b.*\b(data|questions?|words|messages?|chats?|anything|internet|cloud|openai|online)\b|"
                           r"\b(save|saves|keep|keeps|store|stores|log|logs)\b.*\b(my )?(chats?|conversations?|messages?|questions?|words)\b|\b(can|could) (my|anyone|someone|somebody|people|others?)\b.*\b(see|read|access)\b|\bis (this|it|the lab|my data)( \w+)? (private|secure)\b|^\s*is (this|it|the lab|my data) safe\??\s*$|\boffline\b|on a plane|\bsee what i (type|write|ask)\b|without (the )?(internet|wi-?fi)|\bneed (the )?(internet|wi-?fi)\b|who can see", re.I)),
    ("where_models", re.compile(r"\bwhere\b.*\b(models?|files?|saved?|stored?|downloaded|downloads?|put|live|lives|kept|keep)\b|where'?s (it|the)|\b(find|locate|see)\b.*\bmodels?\b.*\b(on|in) (my|this|the)\b|\bwhich folder\b", re.I)),
    ("my_models", re.compile(r"\b(what|which)\b.*\bmodels?\b.*\b(have|got|installed|downloaded|on (my|this))\b|how many models|\blist\b.*\bmodels\b|\bmodels do i\b", re.I)),
    ("status", re.compile(r"\b(is|are)\s+(my model|the model|my models|it|everything|ollama|this|setup)(\s+\w+){0,2}\s+(working|running|ready|installed|ok|okay|set up|done|finished)\b|"
                          r"\b(do|does)\s+(it|my model|the model|this)\s+work\b|\bam i (done|good|ready|set)\b|good to go|next step|what('?s| is| do i do) next|what now|now what|"
                          r"\bis (ollama|it|the model|my model)( even)? on\b|\bnothing (is )?happen\w*|\bactually running\b|\bdid (it|that|this|i) (work|do it right)\b|\bdid the download\b|what do i do now|\bis the thing\b|\b(isn't|is not|not) answering\b|check my (setup|install)|\bmy (setup|install)\b|\b(model|it|ollama) (is|seems|looks) broken\b|\b(isn't|is not|not|doesn't|won't) (work|working|run|running|respond|responding)\b", re.I)),
    ("download_time", re.compile(r"how long (will|does|would|is).*\b(download|install|set ?up)\b|\bdownload\b.*how long", re.I)),
    ("stop_model", re.compile(r"how (do|can) i (stop|quit|close|turn off|shut down|unload)\b.*\b(model|ollama|it)\b", re.I)),
    ("measurements", re.compile(r"what did (i|it|you) (measure|get|score)|what (i|you) measured|\bmy (results|measurements?|numbers|speed)\b|benchmark results|how fast (is|was|are) (my|it)|show .*\bresults\b", re.I)),
    ("slow", re.compile(r"\b(so|too|really|very)? ?slow\b|taking (forever|so long|too long|ages)|\b(why|how come)\b.*\b(long|lag\w*)\b", re.I)),
    ("changed", re.compile(r"what (did|has|have) (the lab|this|it|you)\b.*\b(change|changed|do|done|install|installed|add|added|download|downloaded)\b|what changed|"
                           r"how (do|can) i (remove|uninstall|delete|get rid of|undo)\b(?!.*\b(vs ?code|obsidian)\b)|uninstall (this|the lab|everything|all)|remove everything|clean ?up|\b(taking|using|takes|uses) up\b.*\b(space|room|disk|storage)\b|what'?s taking up|how much (space|disk|room).*\b(use|using|take|taking|taken|up)\b", re.I)),
    ("fit", re.compile(r"\b(which|what) (model|llm)\b|\bwhich one should i\b|recommend|what can my (laptop|computer|machine|mac|pc)|should i (download|use|get)\b|\b(best|biggest|smallest|fastest|smartest|strongest) (of these )?models?\b|which of (these|the) models|\benough (ram|memory)\b|what fits|\bfits? my\b", re.I)),
    ("hardware", re.compile(r"how much (ram|memory|disk|storage)|\b(my|free) (free )?(memory|ram|disk)\b|\bmy (specs?|hardware)\b|(my|this) (laptop|computer|machine|mac|pc)'?s? (specs?|memory|ram|disk|chip|cpu|gpu)\b|what (chip|cpu|gpu|laptop|computer) do i", re.I)),
    ("good_for", re.compile(r"what('?s| is) (it|this|the model|a small model) (good|useful) for|what (should|could|can) i (ask|use|do)|what can (it|this|the model) do|\b(make|makes|making) (stuff|things|facts) up\b|\bhallucinat\w*|\b(as good as|better than|worse than)\b|\bchatgpt\b|"
                            r"what'?s the point|\bis (it|this) free\b|\bhow much (does|will) (it|this) cost\b|how (smart|good|accurate) is|can it (browse|search|see|read|remember|access|learn)|\b(can|should) i trust\b", re.I)),
    ("what_you_do", re.compile(r"what can you do|who are you|what are you\b|how can you help|what('?s| is) (this|the) (lab|site|tool)\b|^\s*(hi|hello|hey)[\s!.?]*$", re.I)),
]
ANSWERS = {"course_rules": lambda lab: COURSE_RULES, "download_time": download_time, "stop_model": stop_model, "health": lambda lab: HEALTH, "recipes": setups, "status": status, "reopen": reopen, "where_models": where_models, "my_models": my_models, "fit": fit, "measurements": measurements,
           "slow": slow, "changed": changed, "hardware": hardware, "last_problem": last_problem,
           "privacy": lambda lab: PRIVACY, "good_for": lambda lab: GOOD_FOR, "what_you_do": lambda lab: WHAT_YOU_DO}
INSTALL_SOMETHING = re.compile(r"^\s*(?:please\s+|can you\s+|could you\s+|how (?:do|can) i\s+)?install\s+(?:the\s+|an?\s+)?(?:app\s+)?([a-z][\w.+-]{1,30})", re.I)
NOT_AN_APP = {"a", "an", "the", "it", "this", "that", "model", "models", "ollama", "app", "apps", "anything", "something", "everything", "more", "another", "new",
              "started", "help", "better", "faster", "going", "me", "my", "one", "them", "from", "stuck", "rid", "to", "on", "in", "any", "some", "vs", "visual", "obsidian"}


def _steps_asked(lab, text):
    """Someone asking the lab to do something. Questions about a thing are not requests to do it."""
    app = _app_for(text)
    step = _step_for(text)
    if app:
        return _ask_for_app(lab, app, step) if step in {"pull_model", "remove_model"} else None
    asking = re.match(r"\s*(why|what|when|where|which|who|does|do|did|is|are|was|were|will|would|how (big|much|long|many|fast))\b", text, re.I)
    if asking and not (_mentioned(lab, text) and re.search(r"how fast", text, re.I)):
        return None
    if re.search(r"\b(ollama)\b", text, re.I):
        if re.search(r"\b(start|open|launch|run)\b", text, re.I):
            return _ask_for_step(lab, "", "start_runtime")
        if re.search(r"\b(install|download|get)\b", text, re.I):
            rt = lab.runtime_state()
            return (_reply("step", "checked", "Ollama is already installed on this laptop.", ["Ollama's server"]) if rt["installed"] else
                    _reply("step", "checked", "You install Ollama yourself, from its official page, and Set up has the link. The lab doesn't run installers for you.", ["Ollama's server"], links=[_link("Go to Set up", "deploy")]))
    tag = _mentioned(lab, text)
    if tag and step:
        return _ask_for_model(lab, tag, step)
    if not tag and step in {"benchmark", "first_prompt", "remove_model"} and len(text) < 60 and re.search(r"\b(it|my model|the model|model|measure|benchmark|hello|hi)\b", text, re.I):
        return _ask_for_step(lab, text, step)
    if not tag and step == "pull_model" and re.search(r"\b(a|the|another|new|first|my) model\b", text, re.I):
        return fit(lab)
    other = INSTALL_SOMETHING.search(text)
    if other and not tag and other.group(1).lower() not in NOT_AN_APP:
        return _other_app(other.group(1))
    return None


# Fixed patterns only catch the wordings someone thought of. A model of 3B or more is good at choosing from a short
# list, so it may choose the check; code still writes every fact. The worst a wrong choice can do is give a true answer to
# the wrong question, and the page offers "Not what I asked" for that. 0.5B and 1.5B each chose correctly only 6 times in 24, so they never do this.
TOPICS = {
    "status": "whether setup is finished, whether Ollama or the model is on or working, what to do next",
    "reopen": "how to open or use the lab again later, after closing or restarting the laptop",
    "where_models": "where model files are stored on the laptop",
    "my_models": "which models are on this laptop",
    "fit": "which model to choose, or whether a model fits this laptop",
    "measurements": "the speed or memory numbers measured so far",
    "slow": "why replies are slow",
    "changed": "what the lab changed or added, how much space it uses, how to remove or uninstall it",
    "hardware": "this laptop's memory, disk, chip or other specs",
    "privacy": "whether anything leaves the laptop, who can see it, whether chats are saved, whether it works offline",
    "good_for": "what a small local model can and can't do, why it makes mistakes, how it compares with ChatGPT, whether it costs money",
    "course_rules": "whether AI may be used for homework, a thesis, exams or a course",
    "health": "the learner is stuck, something isn't happening, or they want help from a TA",
    "recipes": "setting up a laptop for a course, or ready-made setups",
    "none": "anything else: general knowledge, writing, coding or explaining an idea",
}
TOPIC_PROMPT = ("Choose which one topic a beginner's message is about, for a lab that runs small AI models on a laptop. Topics:\n"
                + "\n".join(f"- {k}: {v}" for k, v in TOPICS.items())
                + "\nAnswer as JSON with one topic. Choose none unless the message is clearly about the lab or this laptop.")
ABOUT_THE_LAB = re.compile(r"\b(it|it's|this|my|model|models|ollama|lab|laptop|computer|mac|pc|download\w*|install\w*|files?|folder|memory|ram|space|disk|chats?)\b", re.I)
MAKE_SOMETHING = re.compile(r"\b(write|compose|draft|summari[sz]e|translate|rewrite|poem|haiku|essay|story|recipe for)\b|^\s*(give me|list|explain how|tell me a)\b", re.I)
MIN_PICKER_PARAMS_B = 3.0


def pick(lab, model: str, text: str):
    """Let the model choose a topic from the fixed list. Returns code's answer to that topic, or None for an open question."""
    if lab.allowed[model]["params_b"] < MIN_PICKER_PARAMS_B or not ABOUT_THE_LAB.search(text) or MAKE_SOMETHING.search(text):
        return None
    try:
        names = ChatClient(lab.settings.base_url, model, timeout=60).choose_tools(TOPIC_PROMPT, text, list(TOPICS))
    except LLMError:
        return None
    name = names[0] if names else "none"
    if name not in ANSWERS:
        return None
    return {**ANSWERS[name](lab), "picked_by": model}


def answer(lab, text: str):
    """A reply written by code from real checks, or None when this is an open question for the model."""
    if (COURSE_WORDS.search(text) and COURSE_ASK.search(text)) or COURSE_FOUND_OUT.search(text):
        return COURSE_RULES
    if ERROR_WORDS.search(text) or "\n" in text.strip():
        matches = lab.tools.read_logs(text)["matches"]
        if matches:
            return known_error(lab, matches[0])
        if ERROR_WORDS.search(text):
            if dict(PATTERNS)["last_problem"].search(text):
                return last_problem(lab)
            return UNKNOWN_ERROR if ABOUT_THE_LAB.search(text) else None
    defined = glossary(text)
    if defined:
        return defined
    tag = _mentioned(lab, text)
    if dict(PATTERNS)["health"].search(text):
        return HEALTH
    if dict(PATTERNS)["reopen"].search(text):
        return reopen(lab)
    if dict(PATTERNS)["download_time"].search(text):
        return download_time(lab)
    if dict(PATTERNS)["recipes"].search(text):
        return setups(lab)
    asked = _steps_asked(lab, text)
    if asked:
        return asked
    if tag and not re.search(r"\b(explain|why|write|translate)\b", text, re.I):
        return model_facts(lab, tag)
    for intent, pattern in PATTERNS:
        if pattern.search(text):
            return ANSWERS[intent](lab)
    return None
