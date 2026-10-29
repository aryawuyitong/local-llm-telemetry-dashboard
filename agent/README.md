# Team 14 · Local LLM Lab Assistant (agent + collector)

The agent part of the **Operational Telemetry Dashboard** project (95-891 Intro to AI, Fall 2026).
Learners deploy a small quantized LLM **by hand**; this agent guides them with **five deterministic tools**,
explains what it finds, and refuses unsafe advice. The collector measures the four required metrics
(TTFT, TPS, CPU %, RAM) and writes them in the format the team dashboard reads.

Everything runs on the learner's laptop as a normal user: no admin rights, no cloud, no data uploaded.

> **AI use:** parts of this code were drafted with an AI assistant (Claude) and reviewed and tested by the team.
> Cite this in the final README as the course's genAI policy requires.

## Team quick start (about 10 minutes, no admin)
1. **Install Python 3.9+** from [python.org](https://www.python.org/downloads/). On Windows, tick "Add python.exe to PATH".
2. **Install Ollama** from [ollama.com/download](https://ollama.com/download) and open it once. (Or let the lab walk you through it in step 4.)
3. **Get this folder:** `git clone https://github.com/aryawuyitong/local-llm-telemetry-dashboard.git`, or use GitHub's **Code → Download ZIP** and unzip it.
4. **Start the lab:** open the `agent` folder and double-click:
   - macOS: `Start Lab Helper.command`. If macOS says it can't be opened, right-click it → **Open** → **Open** (first time only).
   - Windows: `Start Lab Helper.bat`. If SmartScreen appears, click **More info → Run anyway**.

   The first run sets up a private Python environment in `agent/.venv` (about 20 s). Then your browser opens the lab.
   Keep the small window open; close it to stop.
5. **In the browser:**
   - **Deploy:** click Allow, pick a goal, pick a model, and approve each step.
   - **Predict & Run:** guess, then measure.
   - **Results:** click **Download runs.csv**, then upload it in the dashboard's sidebar (or copy it into the repo's `results/` folder).
6. **Send Rohan** anything that broke: a screenshot of the step card, or the text in the small window.

Want the terminal version instead? See **Run it** below, and run the commands from inside `agent/`.

## Architecture

```
 learner ──► CLI chat / portal
               │
               ▼
        ┌──────────────┐   secrets redacted
        │  LabAgent     │◄── (guardrails)
        │  agent.py     │
        └──┬────────┬──┘
   router  │        │  LLM (local, via OpenAI-compatible API:
  (rules)  │        │       Ollama or llama.cpp's llama-server)
           ▼        ▼
        ┌────────────────────────── 5 tools (tools.py) ──────────────────────────┐
        │ check_hardware │ check_install │ run_benchmark │ read_logs │ recommend_model │
        └───────┬───────────────┬──────────────┬─────────────┬───────────┬───────┘
          psutil/platform   server + files   collector.py   error_catalog   models.json
                                                 │
                                    results/*.json + results/runs.csv ──► dashboard
        final reply ──► guardrails.check ──► rewrite once ──► scrub if still unsafe
```

| File | What it does |
|---|---|
| `telemetry_agent/agent.py` | The agent loop: router → LLM with tool schemas → tool calls → guarded final reply |
| `telemetry_agent/tools.py` | The 5 tools. **Docstrings are written for the LLM** (when to call, what it returns) |
| `telemetry_agent/router.py` | Rules that run the obvious first tool so a small model can't skip it |
| `telemetry_agent/guardrails.py` | Safety rules on replies; secret redaction; system-prompt rules |
| `telemetry_agent/collector.py` | Benchmark method; writes JSON + dashboard CSV |
| `skill/skill.md` | The agent's playbook (how to teach, ground rules for facts) |
| `skill/error_catalog.json` | 20 known deployment failures with safe fixes |
| `skill/models.json` | Allow-list of models (size, RAM needed, license) |
| `evals/` | 20 scripted failures, 15 red-team prompts, scorer |
| `tests/` | Unit tests (no model server needed) |

## The five tools

| Tool | Purpose (one line) |
|---|---|
| `check_hardware` | Reports OS, CPU architecture, cores, total/free RAM, free disk, GPU, admin status |
| `check_install` | Verifies the manual deployment step by step (python → runtime → server → model → first prompt) and returns the first failing step with a safe fix |
| `run_benchmark` | Runs the standard benchmark on an allow-listed model and returns median TTFT, TPS, CPU %, peak RAM; compares with the learner's guess |
| `read_logs` | Matches pasted errors against the error catalog and returns the cause, safe fix, and concept to learn |
| `recommend_model` | Picks an allow-listed model that fits the laptop's RAM and the 10 GB budget, explains why, and gives a faster and a stronger option |

No tool runs a shell command chosen by the LLM. The learner runs every install command; that's both a safety
property and the project's "learn by doing" requirement.

## Why a router?
A ~3B local model often skips tools or calls the wrong one. In testing, without the router, `qwen2.5:3b`
answered an "address already in use" error from memory (wrong OS, force-killing processes) and reported a
learner's *guess* of 40 tok/s as a measurement. For the common requests the right first tool is obvious
(pasted error → `read_logs`, "how fast is X" → `run_benchmark`, "which model" → `recommend_model`,
"what's next" → `check_install`), so `router.py` runs it first and the LLM only explains the result.
Use `--no-router` to measure the LLM's own tool choice.

## Guardrails
Checked on every final reply (only where text looks like a command, so "you don't need sudo" isn't flagged):

| Rule | Blocks |
|---|---|
| `admin` | `sudo`, `runas`, "Run as administrator" |
| `delete` | `rm`, `del`, `rmdir`, `Remove-Item`, `format`, `dd` |
| `system_files` | `/etc/`, `/System/`, `C:\Windows`, `System32`, registry edits |
| `permissions` | `chmod 777`, `chown` |
| `security_off` | Gatekeeper/SIP/Defender off, machine-wide execution policy, `--break-system-packages`, disabling SSL checks |
| `pipe_to_shell` | `curl … \| sh`, `iwr … \| iex` |
| `kill_process` | `taskkill /F`, `kill -9`, `killall` |
| `not_allow_listed` | `ollama pull` / `hf download` of models not in `models.json` |
| `ask_secret` / `secret_echo` | asking the learner to send a token/password; repeating one |

If a reply breaks a rule the agent is asked to rewrite it once; if it still breaks a rule the offending lines
are replaced with a notice. Secrets in the learner's message are redacted before the LLM sees them.
`--no-guardrails` turns all of this off (and removes the safety rules from the system prompt) for the
with/without comparison.

## Benchmark method
1 warm-up request (reported as `load_time_s`), then each of 3 standard prompts (short / medium / long) ×
repeats, streamed at temperature 0 with at most 128 output tokens. Each run's prompt gets a unique tag so the
runtime can't reuse a cached prompt (without it, repeat TTFTs dropped from ~210 ms to ~36 ms).

- **TTFT** = request sent → first text chunk
- **TPS** = (output tokens − 1) / (last chunk − first chunk)
- **CPU %** = summed CPU of the runtime's processes ÷ logical cores (0–100 % of the machine). Low on Apple Silicon, where the GPU does the work.
- **Peak RAM** = highest summed resident memory (RSS) of the runtime's processes during the run. Newer Ollama versions run inference in a child `llama-server` process, which is included.

`results/runs.csv` uses the dashboard's columns (`machine_label, os, os_version, cpu_model, model_name,
total_ram_gb, n_gpu_layers, run_index, load_time_s, ttft_ms, tps, output_tokens, cpu_percent_normalized,
peak_ram_mb`) plus `tester, runtime, prompt_id, timestamp`.

## Setup (macOS or Windows, normal user)
```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
python -m pip install -r requirements.txt
```
Runtime, either:
- **Ollama** (default): install for your user, open it once, `ollama pull qwen2.5:3b` (agent) and `ollama pull qwen2.5:1.5b` (benchmark).
- **llama.cpp**: unzip the release for your CPU, then `./llama-server -m models/<file>.gguf --jinja --port 8080` and
  `export AGENT_RUNTIME=llama.cpp AGENT_BASE_URL=http://localhost:8080/v1`.

## Run it
```bash
python -m telemetry_agent --trace                       # chat; shows which tools ran
python -m telemetry_agent tool check_install            # one tool, JSON output
python -m telemetry_agent bench --model qwen2.5:1.5b --tester <name> --machine-label <label>
python -m unittest discover -s tests -t .               # unit tests (no server needed)
python evals/run_evals.py all                           # scope metrics: diagnosis + red-team
```
Settings via environment: `AGENT_MODEL` (default `qwen2.5:3b`), `AGENT_BASE_URL`, `AGENT_RUNTIME`,
`MODELS_DIR`, `RESULTS_DIR`, `DISK_BUDGET_GB`, `MACHINE_LABEL`.

## Lab Helper: the website version (no terminal)
For learners who have never used a terminal. Double-click **`Start Lab Helper.command`** (macOS) or
**`Start Lab Helper.bat`** (Windows). The first run sets up a private `.venv` in this folder (about 20 s, no admin).
It then opens the lab in the browser. Keep the small window open while using the lab.

The page has four tabs (Learn · Deploy · Predict & Run · Results) and the assistant on the side.
It uses the same `Toolbox`, router, guardrails and `LabAgent` as the CLI (`telemetry_agent/helper.py`, page in `telemetry_agent/web/`).

- **Deploy:**
  1. Read the laptop's specs, after the learner approves.
  2. Pick a goal: try it, study, write, or code.
  3. `recommend_model` suggests a model for that goal.
  4. Setup steps run as approval cards: install Ollama, start it, download the model, say hello.
  5. Try the model, with time to first token and tokens/s shown.

  Each card shows why the step is needed, what changes on the laptop, and the terminal command it replaces.
- **Predict & Run:** sliders for the learner's speed and RAM guesses → `run_benchmark` → guess vs. actual bars.
- **Results:** medians from `results/runs.csv`, plus a download button for the team dashboard.
- **Assistant:** `LabAgent` chat that shows which tool ran (router or AI), with a safety-layer switch for the demo comparison.
  Before any model is downloaded, it still diagnoses pasted errors with `read_logs`.

**Safety:**
- The helper listens on `127.0.0.1` only and checks the `Host` header.
- Every API call needs a random per-launch token.
- The page can only start 5 fixed actions, each with an allow-listed model. Nothing runs a command from the LLM or the browser.
- Installing Ollama stays a manual step: it opens ollama.com, and the user installs it themselves, for their user only.

Developers: `python -m telemetry_agent.helper` (or `--no-browser --port 8765`).

**v1 limits:**
- The launcher shows a Terminal window.
- A downloaded `.command` needs right-click → Open the first time (Gatekeeper).
- Windows is untested.
- Ollama only, no llama.cpp yet.
- The hosted portal can't call the helper yet: it needs CORS and pairing.

## Evaluation (first run, Oct 26, Apple M5 / 16 GB, qwen2.5:3b via Ollama)
See `EVAL_RESULTS.md`.

## Team to-dos
- [ ] Run `bench` on every teammate's laptop (≥ 1 Windows) and send `results/runs.csv` to the dashboard
- [ ] Replace the scripted failures in `evals/failures.json` with real errors from our own installs
- [ ] Hand-review eval transcripts (`results/evals_*.json`): is each fix actually right?
- [ ] Test the llama.cpp path on Windows (no admin) and fix `check_install` details
- [ ] Verify the sizes/RAM in `models.json` on real laptops
- [x] Predict & Run view → `run_benchmark` with `guess_tps` / `guess_ram_gb` (in the Lab Helper page)
- [ ] Package the Lab Helper as a real app (no Terminal window), test it on Windows, and let the hosted portal pair with it
- [ ] Confirm with Prof. Chung that these 5 tools match the course's definition of custom tools
