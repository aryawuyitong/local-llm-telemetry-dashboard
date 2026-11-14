# Local AI Lab

Local AI Lab helps learners run small language models on their laptops and see how model size affects response time, speed, and resource use.

## Start with the website

Open [Local AI Lab](https://aryawuyitong.github.io/local-llm-telemetry-dashboard/). Once this revision is deployed, **Browser lab** runs a model inside a compatible browser on Windows or macOS. Select a model and click **Run benchmark**. The smaller SmolLM2 model is selected by default. Choose both models to run the same prompts on each and compare preparation time, first visible text, and tokens per second.

**Quick** runs one timed prompt after warm-up. **Standard** runs three prompt lengths, each repeated three times. Each run batch uses one backend. Automatic mode uses WebGPU with shader-f16 support or CPU WebAssembly. To retry after a GPU initialization error, select **CPU** and run again.

- **Recorded demo** opens immediately with recorded results. It requires no model files.
- **Browser lab** requires no source checkout, Python, or Ollama. The first use retrieves model weights and runtime files. SmolLM2 135M weights are approximately 118–182 MB, depending on backend and quantization. The two models together use approximately 391–570 MB in weights, plus runtime and tokenizer assets. The browser can reuse cached files when its storage policy permits. Browser results report backend, preparation time, first visible text, and decode speed. The browser results export has its own format.
- **Desktop lab** uses Ollama for native inference and measures CPU and RAM for Ollama and its child processes. It displays Ollama-reported GPU memory after warm-up when available. GPU utilization percentage is unavailable. The release workflow builds Mac and Windows applications that bundle the helper. See [desktop release instructions](docs/desktop-release.md) for build, signing and device validation.

Browser benchmark prompts and model output are processed on the laptop. The browser loads the pinned runtime from jsDelivr and models from Hugging Face. A live local model needs its weights available on the device. A recorded demo works when model downloads are impractical.

## Measure installed models with the desktop lab

1. Open the desktop Lab Helper and start Ollama. The lab detects supported model tags already stored in Ollama.
2. Use **Catalog** to add any approved model that you want to test. Review and approve its download. Existing compatible model files are reused.
3. In **Measure**, select one to three installed models. Choose **Quick** for three timed prompts per model or **Full** for nine.
4. Approve the benchmark. The lab measures the models one at a time and releases their working memory between measurements. Each model stays installed and has a separate local result file.
5. Review side-by-side results and recent runs in **Measure**. Use the JSON export to share desktop sessions, or open several saved sessions in the public **Results** page to compare. Match settings and prompt counts before comparing.

## Run the website from a developer checkout

From the project root:

```sh
python3 -m http.server 4173 --bind 127.0.0.1 --directory portal
```

Open `http://127.0.0.1:4173/#browser`. On Windows, use `py -3` in place of `python3`. GitHub Pages publishes the static `portal/` directory when changes land on `main`. Native development steps are below.

## How the assistant answers

A small model invents facts, so anything about this laptop is answered by code. A reply comes from one of three places, and it says which:

| Source | When | Who wrote it |
|---|---|---|
| A real check | Is it working, where are my models, which models fit, what did I measure, what changed, how do I reopen it | Code, from this laptop, just now |
| The lab's notes | Course AI rules, privacy, what small models are good for, the glossary, known errors | People, reviewed text |
| The model | Everything else, such as explaining a general idea | The model, and the reply warns it can be wrong |

Fixed patterns catch common wordings instantly. For other wordings about the lab, a model of 3B or more chooses a topic from a fixed list, and code still writes the answer. A student can press **Not what I asked** to send the question straight to the model. See `agent/telemetry_agent/answers.py`.

## The pages

The two versions have different menus, and a strip under the header says which one you're in.

| Website version | Lab version |
|---|---|
| **Home**: choose how to start | **Set up**: the guided steps for your first model |
| **Browser lab**: run a small model with WebGPU or CPU | **Measure**: benchmark one to three installed models |
| **Demo**: click through the lab with nothing installed | **Catalog**: the same catalog, with a button that sets things up |
| **Catalog**: every setup, model and app, with each command, cost and undo | **Use it**: talk to a model, and compare two |
| **Learn**: four hands-on tools and a glossary | **Learn**: the same tools |
| **Results**: what real laptops measured | **My lab**: health check, receipt, help report and log |

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

## Run the native helper from source for development

These commands are for contributors working in a source checkout. Use a regular user account.

### 1. Install and open Ollama; check Python

Install Ollama from its [official download page](https://ollama.com/download) and leave the app running. You also need Python 3.11 or newer. Make sure you have room for Ollama, one model, and the project environment.

- **macOS:** use Terminal or the VS Code terminal. Check Python with `python3 --version`. For a user-account setup, place `Ollama.app` in a folder you own, such as `~/Applications`, and open it there. Decline a request to move it to the system Applications folder or create a system-wide command link. The app bundle contains its own CLI at `Ollama.app/Contents/Resources/ollama`; the helper can use that path. See the [macOS instructions](https://docs.ollama.com/macos).
- **Windows:** use PowerShell or the VS Code terminal. Check Python with `py -3 --version`. Use the official Ollama installer and keep the default per-user location. Open Ollama, then open a new ordinary terminal so it sees the user PATH. Do not choose "Run as administrator." See the [Windows instructions](https://docs.ollama.com/windows).

Check Ollama's current system requirements on its official page before installing.

### 2. Download the project and open its folder

Open a checkout containing `agent/` and `portal/` in your terminal.

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

**Switching models?** An exact tag only needs downloading once. For a model already installed, go straight to the helper's **Measure** page and select it. A new model still needs its one-time download and resource checks.

**The download is only the first check.** In the helper, continue through **Check that everything is in place** and **Say hello to it**. You are ready for the experiment when the helper verifies the installation and shows one local reply. If verification reports an unverified installation footprint, read its specific message and check the project folder, Python environment, Ollama runtime and model location. Do not bypass the resource check.

A different tag such as `qwen2.5:latest` does not count as `qwen2.5:1.5b`. The 10 GiB project cap counts the chosen model plus this lab, its Python environment and Ollama, not unrelated models or a pre-existing Anaconda installation. Actual free disk and current RAM still matter. If `ollama` is not recognized, follow the helper's platform-specific command for your installed app. The benchmark can select a different installed model without restarting the helper; `AGENT_MODEL` controls the tutoring chat model. To change that chat model, restart the helper with the exact tag and open its new private URL.

Before moving on, confirm: the exact model is installed, verification passed, and you got one local reply in the helper.

### 6. Predict, then run the experiment

After the helper's first local reply, record your expected tokens per second and peak memory before the benchmark. Use **Measure** in the local helper to run the fixed prompts.

### 7. See your charts

Review the charts and previous sessions under **Measure**. To keep a copy, use **Download latest JSON** or open the results folder from **My lab**.
