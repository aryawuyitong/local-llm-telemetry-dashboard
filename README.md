# Local AI Lab

Learn how a small language model runs on your own laptop: understand the concepts, set it up one visible step at a time, predict its behavior, and interpret repeatable measurements. This is an educational prototype built on the team's original local-agent demo.

The repository includes a static learning portal, a local assistant with five custom tools plus one that only proposes an approval card, an Ollama telemetry collector, and evaluation materials. Model inference stays on loopback. The portal processes imported files in browser memory and has no upload service, account, analytics, or external JavaScript dependencies.

## Start here

There is **one website, in two modes**. The [public version](https://aryawuyitong.github.io/local-llm-telemetry-dashboard/) works immediately for lessons, quizzes, and synthetic examples. When you start the Lab Helper on your own computer, it serves the same site from your laptop with setup, downloads, the assistant, and your results working. For a real model run, use a standard user account and follow these steps:

1. Install and open [Ollama](https://ollama.com/download) using its official instructions. The lab needs **Python 3.11 or newer**. On a Mac, the website's start guide walks you from the download to the lab opening: it starts **Start Lab on Mac.command**, at the top of the folder, from Terminal with one pasted line. If you start the lab and your computer has no suitable Python, the launcher shows what it would download (an official CPython 3.12 build from [python-build-standalone](https://github.com/astral-sh/python-build-standalone), about 25 MB on Mac and 45 MB on Windows, checked against its published SHA-256) and waits for you to press Return before it puts that copy in `agent/.python/`. Delete that folder to undo it. Installation from a completely unprepared computer is not yet a verified no-admin workflow. If your organization requires administrator approval or the OS blocks an executable, stop and use its supported process; do not disable protections.
2. Download the [ZIP of `main`](https://github.com/aryawuyitong/local-llm-telemetry-dashboard/archive/refs/heads/main.zip) and extract it, or clone the repository. You may rename the extracted folder `local-ai-lab` and place it at `Desktop/i2ai/project/local-ai-lab`. If you already downloaded it, keep your folder. Open the folder containing `agent/` and `portal/` in VS Code, then choose **Terminal → New Terminal**.
3. From that project-root terminal, enter `agent/`, create an isolated Python environment, and install its listed dependency:

macOS:

```sh
cd agent
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
AGENT_MODEL=qwen2.5:1.5b .venv/bin/python -m telemetry_agent.helper
```

Windows PowerShell:

```powershell
cd agent
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:AGENT_MODEL = 'qwen2.5:1.5b'
.\.venv\Scripts\python.exe -m telemetry_agent.helper
```

4. Keep the terminal open. The helper normally opens its local browser page automatically; if it does not, open the private `http://127.0.0.1:.../#t=...` link printed in the terminal. Do not share that link. The helper works **before a model exists**. Installing Ollama stays with you, on its official page. Nothing else runs until you approve its card.
5. In the helper, check hardware, choose a goal, and review the model recommendation and project disk budget. Each step shows its exact command. Approve the card and the helper runs it, or choose **I'll type it myself**, run the command in a second terminal, and let the helper check. For example, `llama3.2:1b` needs `ollama pull llama3.2:1b`; `llama3.2:latest` is a different tag. Tags are mutable: verify the publisher, applicable license, reported digest, actual download size, and available memory. No model weights are included here.
6. After downloading, approve the check and **Say hello** steps. If the check reports a problem, follow its specific message; do not bypass the resource check. Once you get one local reply, make a speed and memory guess in **Predict & Run**, then approve **Measure**.
7. Open **Results** in the lab. Your latest anonymous session appears in the charts automatically and stays on your laptop. Use **Download JSON** to keep or share a copy, and **Import JSON** on the public site to view it there. Do not import raw logs or personal records.

To compare another model, open the helper's **Predict & Run** view and choose any already installed approved model from its Model menu. Each exact model tag needs to be downloaded only once. For a new tag, set it up from its card on **Models**. The benchmark can select a different installed model without restarting the helper; `AGENT_MODEL` controls which model powers the assistant.

To compare two models in the public Results charts, benchmark each model locally under the same settings. Open **Import JSON** and select both saved session files from `agent/results/` in one selection. Chart rows identify the model. Compare the session conditions and data quality flags before interpreting the medians. This is a speed and resource comparison; benchmark responses are not recorded, so the charts cannot score answer quality. The Results page remains empty until you import measured data or explicitly choose labeled synthetic examples.

The `.command`/`.bat` launchers are optional conveniences after reviewing them. Use the explicit interpreter commands above when activation scripts are blocked; no execution-policy change is needed. The public website and private helper stay separate; closing Ollama or the helper terminal ends local inference.

If an old helper tab says **Failed to fetch** after you download a model, check the terminal where the helper was running. If it says **Stopped.**, restart the helper from `agent/` and open the new private link printed in that terminal; the old tab has an expired session token. Pulling a model in a second terminal does not restart the helper. Model files and completed benchmark JSON files remain on disk.

## Open the learning website

Visit the public [Local AI Lab website](https://aryawuyitong.github.io/local-llm-telemetry-dashboard/) to use the lessons, the demo, synthetic examples, and local JSON import. GitHub Pages publishes the static `portal/` directory when it changes on `main`. No Python or model is needed for these browser features.

To run the same website locally instead, from the repository root:

```sh
python3 -m http.server 4173 --bind 127.0.0.1 --directory portal
```

On Windows replace `python3` with `py -3`. Open `http://127.0.0.1:4173`. The four views are **Learn → Deploy → Predict & Run → Results**. Try the clearly labeled synthetic examples to explore charts before a real experiment. Example numbers are invented and are not project evidence.

The public website never connects to localhost APIs or starts inference. The working lab is the same site served by the helper from your laptop, so it needs no cross-site access; manual JSON export/import remains available for the public site. Do not paste the helper's private session URL or token into the public website.

## How the assistant answers

A small model invents facts, so anything about this laptop is answered by code. A reply comes from one of three places, and it says which:

| Source | When | Who wrote it |
|---|---|---|
| A real check | Is it working, where are my models, which models fit, what did I measure, what changed, how do I reopen it | Code, from this laptop, just now |
| The lab's notes | Course AI rules, privacy, what small models are good for, the glossary, known errors | People, reviewed text |
| The model | Everything else, such as explaining a general idea | The model, and the reply warns it can be wrong |

Fixed patterns catch common wordings instantly. For other wordings about the lab, a model of 3B or more chooses a topic from a fixed list, and code still writes the answer. A student can press **Not what I asked** to send the question straight to the model. See `agent/telemetry_agent/answers.py`.

## Starting the lab on a Mac

macOS blocks a double-click on the launcher, because the lab isn't signed. The website's **start guide** (Home, then "Open the start guide") handles this without changing any security setting. It has five steps, each with a drawing of what the student should see and an "I see something else" button with the fixes for that step.

The guide gives one line to paste into Terminal. It runs `Start Lab on Mac.command`, a five-line file at the top of the folder that opens the real launcher in `agent/`. The line only starts the file that was already downloaded. A Windows guide isn't written yet.

## The pages

The two versions have different menus, and a strip under the header says which one you're in.

| Website version | Lab version |
|---|---|
| **Home**: what your laptop can run, and the download | **Set up**: the guided steps for your first model |
| **Demo**: click through the lab with nothing installed | **Catalog**: the same catalog, with a button that sets things up |
| **Catalog**: every setup, model and app, with each command, cost and undo | **Use it**: talk to a model, and compare two |
| **Learn**: four hands-on tools and a glossary | **Measure**: guess, measure and read the charts on one page |
| **Results**: what real laptops measured | **My lab**: health check, receipt, help report and log |
| | **Learn**: the same tools |

Old links to Models, Apps and Predict & Run still work and open the new pages.

**The catalog** is generated from the action registry and `agent/skill/recipes.json` into `portal/catalog-data.js`, so the public page shows exactly the steps the lab would run. A future setup, such as a cloud database, would be listed the same way.

**Real results** come from anonymous results files that people chose to share, in `evaluation/measurements/`. The script validates each file, recomputes its numbers from the individual runs and writes `portal/measured-data.js`. The Home picker and the Catalog read from it. The lab never uploads anything: a student downloads their file and sends it. See [evaluation/measurements/README.md](evaluation/measurements/README.md). So far the files are from one kind of laptop.

## How it works, hands-on

The Learn page has four small tools instead of a quiz: a memory slider that shows which models fit, a reply played at real recorded speeds, the five stops a question passes through, and a real approval card with every part explained. Each opens with a guess and then shows the answer. Nothing is scored or saved.

The ten-question quiz is off the site for now. Its questions stay in `evaluation/pilot-kit/quiz-and-key.md` for pilots, and its code stays in `portal/app.js`, hidden by the `quiz-off` class.

## The public demo

The public site has a **Demo** page: a visitor clicks through the lab with nothing installed. It shows the approval cards with their costs, a conversation, a two-model comparison and the "what changed" log with Undo. It's marked as a demo throughout.

- The cards are built by the lab's own registry, so their words, commands and costs can't drift from the product. `scripts/sync_portal_data.py` writes them to `portal/preview-data.js`, and the project check fails if that file is stale.
- Every reply and number was recorded from a real run on one laptop, including the wrong answers. They live in `agent/skill/preview_samples.json`. Re-record them with a running helper, and never edit one by hand.

## Use it, compare, recipes and health

- **Use it** is a real conversation with any model on the laptop, with starter prompts for each goal. It also lists what small models get wrong, reminds students to check their course's AI rules, and says how to come back tomorrow. Nothing typed there is saved.
- **Compare two models** asks both the same question, one at a time, with fixed settings and nothing else in memory. The student judges the answers, because a speed number can't.
- **Risk labels:** every card states its time, space, internet, password, money and undo. A card without all six can't be built, so a future cloud action has to state its cost.
- **Recipes** are reviewed lists of registered steps, ending in one check. They hold no commands, so a TA can write one without touching code. See [docs/recipes.md](docs/recipes.md).
- **Health check** in My lab re-runs every check, changes nothing, and offers a repair card for what it can repair. **Help report** makes one page for a TA, with no typed words, replies, files, name or measurements. The student reads it first, and the lab never sends it.

## Apps, receipts and pilots

- **Apps** (lab mode): the same approval cards install Visual Studio Code or Obsidian through Homebrew on a Mac or winget on Windows. The command on the card is the command that runs, the install is logged in My lab with Undo, and without Homebrew or winget the step becomes a manual one from the app's official page. Only these two apps can be named; the assistant can propose them but never run them.
- **Receipt** (My lab): one Markdown page listing everything the lab added to the laptop, where it is, how much space it takes, and how to remove each item. Download it before deleting the lab folder.
- **Pilot kit**: `evaluation/pilot-kit/` has a 45-minute protocol, an observation sheet, a timing log and the frozen quiz with its key, so any teammate can run a pilot. A website test keeps the key identical to the site's quiz.

## What the assistant can do

| Custom tool | Bounded behavior |
| --- | --- |
| `check_hardware` | Read OS/architecture, CPU, total/available RAM, free disk, and account privilege status. |
| `check_install` | Check Python, runtime, loopback server, approved model inventory, and first response in order. |
| `recommend_model` | Compare an explicit allow-list against available memory, free disk, and the project's model budget. |
| `read_logs` | Match a short pasted, redacted error to causes, safe next steps, and the relevant concept. |
| `run_benchmark` | Run approved local inference with fixed prompts and record measurements and missing values. |

A deterministic router selects an obvious first tool; the local LLM can then choose tools and explain their output. Traces identify `router` versus `llm` choices. A skill folder contains the teaching playbook, model metadata, and error catalog. Tool arguments, runtime URLs, local helper requests, and final advice are validated separately. No LLM-selected shell command is executed.

The runtime endpoint must be literal loopback (or normalized `localhost`), without credentials, proxies, redirects, or arbitrary paths. The helper binds to `127.0.0.1`, validates Host and Origin, and requires a per-launch token for its APIs. Keep its token private. Local inference does not make copied text intrinsically anonymous: review exports and never enter credentials or private documents.

## Measurement and resource boundaries

The baseline is **Ollama**, one model at a time, 2,048 context tokens, temperature 0, at most128 output tokens, one excluded warm-up and three fixed prompt classes repeated three times. The export preserves runtime version, model digest, quantization, acceleration facts where available, timing sources, sampling methods, status, and quality flags.

- **TTFT proxy:** client request start to first nonempty response text, not an independently verified token boundary.
- **Decode TPS:** native output-token count divided by native decode duration. Stream chunks are never counted as tokens.
- **CPU:** attributable runtime process-tree CPU time, normalized by logical core count; GPU utilization is not measured. The Results record shows whether Ollama reported GPU offload for the running model, where available. This is an acceleration status, not a GPU utilization percentage.
- **RAM:** sampled process-tree peak RSS in MiB; shared pages can be double-counted and dedicated GPU memory is excluded.

Missing attribution or runtime timing remains `null`. Failed and partial attempts are retained, and the portal recomputes statistics from available non-error run values. Background work, caching, memory pressure, thermal state, and acceleration limit cross-device comparisons.

The provisional 10 GiB **project** budget covers this lab, its project Python environment, the runtime distribution, and the one selected model. A pre-existing base Python/Anaconda installation and unrelated Ollama models are reported or treated as prerequisites, not charged to this project's allowance. The helper still checks actual free disk (including a 2 GiB reserve), current available RAM, the selected model's runtime-reported size and digest, and complete project/runtime inventory before inference. Unknown/incomplete inventories produce a supported stop rather than a false budget pass. For a portable runtime set `RUNTIME_INSTALL_DIR` to its **whole distribution directory**, and set `OLLAMA_MODELS` to its actual model directory. The helper does not remove existing models or files. The model catalog contains estimates, not pinned release artifacts. llama.cpp remains an unsupported/stretch execution path until a trusted file manifest and native decode timing adapter are validated.

See [architecture](docs/architecture.md), [measurement protocol](docs/measurement-protocol.md), [export schema](docs/schema-v1.json), [portal details](portal/README.md), and [current verification evidence](docs/validation.md).

## Tests and evaluation

```sh
python3 -m pip install -r agent/requirements.txt
```

From `agent/` run `python3 -m unittest discover -s tests -t . -v`. From the root:

```sh
python3 -m unittest discover -s evaluation/tests -v
python3 scripts/check_project.py
npm test
```

Node20+ is required only for front-end tests, not to use the portal. CI runs Python tests on Linux, macOS, and Windows with Python3.11/3.13, plus the portal's dependency-free data tests. OS CI is not evidence of a physical Windows model deployment.

[Evaluation instructions](evaluation/README.md) include20 diagnosis candidates,15 adversarial prompts, guarded/unguarded text-only collection, blank independent-review sheets, and pilot/platform record templates. Pending judgments never count as passes. Historical demo scores in `agent/EVAL_RESULTS.md` are development history, not the new acceptance results. Independent human review, real Windows/macOS deployment, and novice learning outcomes remain separate requirements.

## Attribution and project status

The original agent demo and repository history are preserved. No client name, private scope document, participant data, model weights, or local runtime binaries are published here. Dependencies and model licenses remain with their respective authors. This repository does not grant additional model rights.

## Do it all by hand (the full 7 steps)

The website's **Start** page walks you through setup with the Lab Helper. If you would rather run every step yourself, here is the whole route. Use a normal user account. If any step asks for an administrator password or to turn off a security feature, stop and use your device's approved process; do not bypass its protections.

### 1. Install and open Ollama; check Python

Install Ollama from its [official download page](https://ollama.com/download) and leave the app running. You also need Python 3.11 or newer. Make sure you have room for Ollama, one model, and the project environment.

- **macOS:** use Terminal or the VS Code terminal. Check Python with `python3 --version`. For a user-account setup, place `Ollama.app` in a folder you own, such as `~/Applications`, and open it there. Decline a request to move it to the system Applications folder or create a system-wide command link. The app bundle contains its own CLI at `Ollama.app/Contents/Resources/ollama`; the helper can use that path. See the [macOS instructions](https://docs.ollama.com/macos).
- **Windows:** use PowerShell or the VS Code terminal. Check Python with `py -3 --version`. Use the official Ollama installer and keep the default per-user location. Open Ollama, then open a new ordinary terminal so it sees the user PATH. Do not choose "Run as administrator." See the [Windows instructions](https://docs.ollama.com/windows).

Check Ollama's current system requirements on its official page before installing.

### 2. Download the project and open its folder

Download the [ZIP of the main branch](https://github.com/aryawuyitong/local-llm-telemetry-dashboard/archive/refs/heads/main.zip) and extract it. You may rename the extracted folder `local-ai-lab`; for example, `Desktop/i2ai/project/local-ai-lab` is fine. Open that folder in VS Code, then choose **Terminal → New Terminal**. The folder should contain `agent/` and `portal/`. If it does not, open the inner project folder.

Already downloaded it? Keep your existing folder and continue with step 3. You do not need to download it again.

### 3. Prepare the Lab Helper

In the VS Code terminal, run the commands below from the project folder. `cd agent` moves you into the folder containing `requirements.txt`. The remaining commands create a private Python environment and install the one listed dependency.

macOS Terminal (start in the project folder):

```sh
cd agent
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Windows PowerShell (start in the project folder):

```powershell
cd agent
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

If your terminal already shows `agent` as the current folder, skip `cd agent`. Dependency installation needs internet access; it does not download a model.

### 4. Start the private Lab Helper

In the same terminal, run the command below. It starts with the example chat model `qwen2.5:1.5b`, even before that model is downloaded. Keep this terminal open. Your browser should open the local helper automatically; otherwise, open the private URL printed in the terminal. It starts with `http://127.0.0.1` and includes a session token. Do not share that URL.

macOS (run in `agent/`):

```sh
AGENT_MODEL=qwen2.5:1.5b .venv/bin/python -m telemetry_agent.helper
```

Windows PowerShell (run in `agent/`):

```powershell
$env:AGENT_MODEL = "qwen2.5:1.5b"
.\.venv\Scripts\python.exe -m telemetry_agent.helper
```

The page that opens is this same website, running from your laptop, with setup, downloads, the assistant and your results working.

If that terminal later says **Stopped.**, restart the helper and open its new private link. An old helper tab can show **Failed to fetch** after the server stops; refreshing that old tab cannot restore its previous session token. Your model downloads and saved measurements remain on disk.

### 5. Download and verify the exact model

In the **local helper**, choose **Run this check**, select a goal, and review the suggested model. On the download step, choose **Approve and run**, or choose **I'll type it myself**, run the exact command shown in a **second terminal**, and wait for `success`. For example, if you selected `qwen2.5:1.5b`, run `ollama pull qwen2.5:1.5b`. Then click **I ran it; check my work**.

**Switching models?** An exact tag only needs downloading once. For a model already installed, go straight to the helper's **Predict & Run** view and choose it from the Model menu. A new model still needs its one-time download and resource checks.

**The download is only the first check.** In the helper, continue through **Check that everything is in place** and **Say hello to it**. You are ready for the experiment when the helper verifies the installation and shows one local reply. If verification reports an unverified installation footprint, read its specific message and check the project folder, Python environment, Ollama runtime and model location. Do not bypass the resource check.

A different tag such as `qwen2.5:latest` does not count as `qwen2.5:1.5b`. The 10 GiB project cap counts the chosen model plus this lab, its Python environment and Ollama, not unrelated models or a pre-existing Anaconda installation. Actual free disk and current RAM still matter. If `ollama` is not recognized, follow the helper's platform-specific command for your installed app. The benchmark can select a different installed model without restarting the helper; `AGENT_MODEL` controls the tutoring chat model. To change that chat model, restart the helper with the exact tag and open its new private URL.

Before moving on, confirm: the exact model is installed, verification passed, and you got one local reply in the helper.

### 6. Predict, then run the experiment

After the helper's first local reply, record your expected tokens per second and peak memory before the benchmark. Use **Predict & Run** in the local helper to run the fixed prompts.

### 7. See your charts

Open **Results** in the lab. Your latest measurement appears in the charts automatically and stays on your laptop. To keep a copy or share it, use **Download JSON**.
