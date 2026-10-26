# local-llm-telemetry-dashboard

Benchmark small open-weight LLMs running **locally on laptops** (Windows / macOS) and compare
operational telemetry across machines and models in a Streamlit dashboard.

Metrics collected per run:

| Metric | Meaning |
|---|---|
| **TTFT** (ms) | Time to first token — how long before the model starts answering |
| **TPS** (tok/s) | Tokens per second during generation (excludes prompt processing) |
| **Peak RAM** (MB) | Highest process memory, sampled every 50 ms during generation |
| **CPU %** | Process CPU use, normalized to the number of logical cores |
| **Load time** (s) | Time to load the model file into memory |

## 1. Setup

```bash
python -m venv .venv
# macOS / Linux:  source .venv/bin/activate
# Windows:        .venv\Scripts\activate
pip install -r requirements-benchmark.txt   # to run benchmarks + dashboard
# or: pip install -r requirements.txt       # dashboard only (also used by Streamlit Cloud)
```

> `llama-cpp-python` compiles on install. On Windows you may need the
> "Desktop development with C++" workload from Visual Studio Build Tools.

## 2. Download a model

Put a **GGUF** model file in a `models/` folder. Step-by-step instructions (Hugging Face, Kaggle,
official websites) are in the dashboard's **"How to Download a Local LLM"** tab.

## 3. Run the benchmark

```bash
python benchmark_telemetry.py --model ./models/qwen1_5-1_8b-chat-q4_k_m.gguf \
    --runs 3 --tester YOUR_NAME --machine-label "YOUR-LAPTOP"
```

Useful options:

- `--runs 3` — measured runs (1 warm-up run is done first and not recorded; change with `--warmup`)
- `--n-gpu-layers -1` — offload to GPU (e.g. Metal on Apple Silicon); default `0` = CPU only
- `--max-tokens 256`, `--n-ctx 2048`, `--n-threads 4`
- `--output results/benchmarks.csv` — CSV file results are appended to
- `--quiet` — hide the generated text

Each run appends one row to `results/benchmarks.csv`, including machine info
(OS, CPU, RAM), so results from different laptops can be combined.

## 4. Open the dashboard

```bash
streamlit run app.py
```

- Reads every CSV in `results/` automatically.
- Upload teammates' CSV files in the sidebar to compare machines.
- Tabs: **Overview** (median per machine × model), **Compare** (charts), **Raw data** (download), **How to Download a Local LLM**.
- If there are no results yet, it shows clearly-labeled **demo data** from `sample_data/` so you can see the layout.

## Team workflow

1. Everyone runs the benchmark on their own laptop with the same model(s) and prompt.
2. Rename your output file, e.g. `results/gloria_macbook.csv`, and commit it (or share it).
3. Open the dashboard to compare.
