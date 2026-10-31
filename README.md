# Local AI Lab

Learn how a small language model runs on your own laptop: understand the concepts, deploy it manually, predict its behavior, and interpret repeatable measurements. This is an educational prototype built on the team's original local-agent demo.

The repository includes a static learning portal, a separate local assistant with five custom tools, an Ollama telemetry collector, and evaluation materials. Model inference stays on loopback. The portal processes imported files in browser memory and has no upload service, account, analytics, or external JavaScript dependencies.

## Start here

You need a **standard user account, Python 3.11 or newer**, and an officially obtained Ollama installation compatible with your device. Installation from a completely unprepared computer is not yet a verified no-admin workflow. If your organization requires administrator approval or the OS blocks an executable, stop and use its supported installation process; do not disable protections.

1. Download this repository or clone it, then open a terminal in its `agent` directory.
2. Create an isolated Python environment and install the one dependency:

macOS:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m telemetry_agent.helper
```

Windows Command Prompt:

```bat
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m telemetry_agent.helper
```

3. Open the local URL printed by the helper, including its session fragment. The helper works **before a model exists**: inspect hardware and follow the manual deployment checklist. It does not install a runtime or download a model for you.
4. Review the budget and model recommendation, start your installed runtime, and manually obtain one exact approved model tag. A small candidate is `qwen2.5:1.5b`; assistant chat defaults to `qwen2.5:3b` and needs that model installed. To use the same smaller model for chat, set `AGENT_MODEL=qwen2.5:1.5b` before starting the helper. Tags are mutable: check the publisher, applicable license, reported digest, actual download size, and available memory. No model weights are included here.
5. Enter a TPS and RAM prediction, run the standard experiment, then download its anonymous JSON from the local Results view.
6. Open the learning portal separately and import that JSON. Do not import raw logs or personal records.

The `.command`/`.bat` launchers are optional conveniences after reviewing them. Use the explicit interpreter commands above when activation scripts are blocked; no execution-policy change is needed.

## Open the learning website

From the repository root:

```sh
python3 -m http.server 4173 --bind 127.0.0.1 --directory portal
```

On Windows replace `python3` with `py -3`. Open `http://127.0.0.1:4173`. The four views are **Learn → Deploy → Predict & Run → Results**. Try the clearly labeled synthetic examples to explore charts before a real experiment. Example numbers are invented and are not project evidence.

The static website and helper have separate roles. The website never connects to localhost APIs or starts inference. Move results between them by explicitly downloading and importing JSON. The static `portal/` directory is ready for static hosting, but this change does not publish a hosted site.

## What the assistant can do

| Custom tool | Bounded behavior |
| --- | --- |
| `check_hardware` | Read OS/architecture, CPU, total/available RAM, free disk, and account privilege status. |
| `check_install` | Check Python, runtime, loopback server, approved model inventory, and first response in order. |
| `recommend_model` | Compare an explicit allow-list against memory and the measured total installation budget. |
| `read_logs` | Match a short pasted, redacted error to causes, safe next steps, and the relevant concept. |
| `run_benchmark` | Run approved local inference with fixed prompts and record measurements and missing values. |

A deterministic router selects an obvious first tool; the local LLM can then choose tools and explain their output. Traces identify `router` versus `llm` choices. A skill folder contains the teaching playbook, model metadata, and error catalog. Tool arguments, runtime URLs, local helper requests, and final advice are validated separately. No LLM-selected shell command is executed.

The runtime endpoint must be literal loopback (or normalized `localhost`), without credentials, proxies, redirects, or arbitrary paths. The helper binds to `127.0.0.1`, validates Host and Origin, and requires a per-launch token for its APIs. Keep its token private. Local inference does not make copied text intrinsically anonymous: review exports and never enter credentials or private documents.

## Measurement and resource boundaries

The baseline is **Ollama**, one model at a time, 2,048 context tokens, temperature 0, at most128 output tokens, one excluded warm-up and three fixed prompt classes repeated three times. The export preserves runtime version, model digest, quantization, acceleration facts where available, timing sources, sampling methods, status, and quality flags.

- **TTFT proxy:** client request start to first nonempty response text, not an independently verified token boundary.
- **Decode TPS:** native output-token count divided by native decode duration. Stream chunks are never counted as tokens.
- **CPU:** attributable runtime process-tree CPU time, normalized by logical core count; GPU utilization is not measured.
- **RAM:** sampled process-tree peak RSS in MiB; shared pages can be double-counted and dedicated GPU memory is excluded.

Missing attribution or runtime timing remains `null`. Failed and partial attempts are retained, and the portal recomputes statistics from available non-error run values. Background work, caching, memory pressure, thermal state, and acceleration limit cross-device comparisons.

The provisional10 GiB budget covers the project, Python environment, runtime distribution, and all installed model sizes. Unknown/incomplete inventories produce a supported stop rather than a false budget pass. For a portable runtime set `RUNTIME_INSTALL_DIR` to its **whole distribution directory**, and set `OLLAMA_MODELS` to its actual model directory. Old unrelated installations can exceed the budget; do not delete them automatically. The model catalog contains estimates, not pinned release artifacts. llama.cpp remains an unsupported/stretch execution path until a trusted file manifest and native decode timing adapter are validated.

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

The original agent demo and repository history are preserved. This implementation was developed with Codex assistance, including code, tests, documentation, and interface work; the team should review it and disclose AI use according to course rules. No client name, private scope document, participant data, model weights, or local runtime binaries are published here. Dependencies and model licenses remain with their respective authors. This repository does not grant additional model rights.
