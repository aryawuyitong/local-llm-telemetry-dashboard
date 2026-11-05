# Local AI Lab

Learn how a small language model runs on your own laptop: understand the concepts, deploy it manually, predict its behavior, and interpret repeatable measurements. This is an educational prototype built on the team's original local-agent demo.

The repository includes a static learning portal, a separate local assistant with five custom tools, an Ollama telemetry collector, and evaluation materials. Model inference stays on loopback. The portal processes imported files in browser memory and has no upload service, account, analytics, or external JavaScript dependencies.

## Start here

There are **two pages**: the [public learning website](https://aryawuyitong.github.io/local-llm-telemetry-dashboard/) and a private Lab Helper that runs on your own computer. The public website works immediately for lessons, quizzes, and synthetic examples. For a real model run, use a standard user account and follow these steps:

1. Install and open [Ollama](https://ollama.com/download) using its official instructions. Confirm you have **Python 3.11 or newer** with `python3 --version` on macOS or `py -3 --version` on Windows. Installation from a completely unprepared computer is not yet a verified no-admin workflow. If your organization requires administrator approval or the OS blocks an executable, stop and use its supported process; do not disable protections.
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

4. Keep the terminal open. The helper normally opens its local browser page automatically; if it does not, open the private `http://127.0.0.1:.../#t=...` link printed in the terminal. Do not share that link. The helper works **before a model exists** and does not install Ollama or download a model for you.
5. In the helper, check hardware, choose a goal, and review the model recommendation and project disk budget. When it says **Manually download [model]**, keep the helper terminal open and run the exact command shown in a second terminal. For example, `llama3.2:1b` needs `ollama pull llama3.2:1b`; `llama3.2:latest` is a different tag. Wait for `success`, run `ollama list` to verify the exact tag, then click **I completed this step; check again** in the helper. If Ollama's command is not on your PATH, follow the helper's command for your installed app. If you choose a different model from `AGENT_MODEL`, restart the helper with that exact tag for assistant chat. Tags are mutable: verify the publisher, applicable license, reported digest, actual download size, and available memory. No model weights are included here.
6. After downloading, continue through **Verify the manual steps** and **Run a bounded first prompt** in the helper. If verification reports an unverified installation footprint, follow its specific message and check the project folder, Python environment, Ollama runtime, and model location; do not bypass the resource check. If you restart the helper with a different `AGENT_MODEL`, open its newly printed private URL. Once verification passes and you get one local response, make a TPS and RAM prediction before using **Predict & Run** for the benchmark. In **Results**, download the anonymous session JSON.
7. In the helper's **Results** view, click **Open charts in public website**. It opens the [public Results view](https://aryawuyitong.github.io/local-llm-telemetry-dashboard/#results) and transfers the latest anonymous session directly between browser tabs; no result is uploaded to a server. If the new tab is blocked, use **Download JSON instead**, then **Import JSON** on the public page. Do not import raw logs or personal records.

### Optional: Auto setup (asks you to confirm)

After Ollama is installed and running (step 1 stays manual), you can press **Auto setup** on the helper's Learn page, or **Use Auto setup** in Deploy, instead of steps 5–6. Auto picks the planning candidate for your goal and shows a confirmation panel with the model, download size, free disk, source and license. Nothing happens until you tick the box and press **Confirm**. Then it asks your local Ollama to download that exact allow-listed tag through Ollama's `/api/pull`, runs the same verification and first prompt as the manual path, and opens a chat box for the model.

How the confirmation works: `/api/auto/plan` is read-only and returns a single-use confirmation code that expires after 5 minutes. `/api/auto/start` runs only with that code, and the code names the model, so a request cannot swap in another model or skip the review. Auto never installs programs, runs shell commands, requests admin rights, bypasses the budget/digest checks, or deletes files, and `/api/jobs` still rejects download actions. It is less transparent than the manual path because you approve one plan instead of each command. Use the manual steps when the lesson is the setup itself.

To compare another model, open the helper's **Predict & Run** view and choose any already installed approved model from its Model menu. Each exact model tag needs to be downloaded only once. For a new tag, use the **Copy command** button in Deploy, run that command in a second terminal, then return to the helper and click **I completed this step; check again**. The benchmark can select a different installed model without restarting the helper; `AGENT_MODEL` controls which model powers the tutoring chat.

To compare two models in the public Results charts, benchmark each model locally under the same settings. Open **Import JSON** and select both saved session files from `agent/results/` in one selection. Chart rows identify the model. Compare the session conditions and data quality flags before interpreting the medians. This is a speed and resource comparison; benchmark responses are not recorded, so the charts cannot score answer quality. The Results page remains empty until you import measured data or explicitly choose labeled synthetic examples.

The `.command`/`.bat` launchers are optional conveniences after reviewing them. Use the explicit interpreter commands above when activation scripts are blocked; no execution-policy change is needed. The public website and private helper stay separate; closing Ollama or the helper terminal ends local inference.

If an old helper tab says **Failed to fetch** after you download a model, check the terminal where the helper was running. If it says **Stopped.**, restart the helper from `agent/` and open the new private link printed in that terminal; the old tab has an expired session token. Pulling a model in a second terminal does not restart the helper. Model files and completed benchmark JSON files remain on disk.

## Open the learning website

Visit the public [Local AI Lab website](https://aryawuyitong.github.io/local-llm-telemetry-dashboard/) to use the lessons, quizzes, synthetic examples, and local JSON import. GitHub Pages publishes the static `portal/` directory when it changes on `main`. No Python or model is needed for these browser features.

To run the same website locally instead, from the repository root:

```sh
python3 -m http.server 4173 --bind 127.0.0.1 --directory portal
```

On Windows replace `python3` with `py -3`. Open `http://127.0.0.1:4173`. The four views are **Learn → Deploy → Predict & Run → Results**. Try the clearly labeled synthetic examples to explore charts before a real experiment. Example numbers are invented and are not project evidence.

The public website and local helper have separate roles. The website never connects to localhost APIs or starts inference. A user-initiated button can pass one anonymous result from the helper tab to the public Results tab for in-browser charts; manual JSON export/import remains available. Do not paste the helper's private session URL or token into the public website.

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

The original agent demo and repository history are preserved. AI assistance was used to develop the code, tests, documentation, and interface; the team should review this work and disclose AI use according to course rules. No client name, private scope document, participant data, model weights, or local runtime binaries are published here. Dependencies and model licenses remain with their respective authors. This repository does not grant additional model rights.
