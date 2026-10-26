"""
Local LLM Telemetry Dashboard (Streamlit).

Reads every CSV in ./results/ (written by benchmark_telemetry.py) plus any CSVs
uploaded in the sidebar, and compares performance across machines and models.

Run:  streamlit run app.py
"""

import glob
import os

import altair as alt
import pandas as pd
import streamlit as st

RESULTS_DIR = "results"
DEMO_FILE = os.path.join("sample_data", "demo_results.csv")
NUMERIC_COLS = ["ttft_ms", "tps", "peak_ram_mb", "cpu_percent_normalized", "load_time_s",
                "output_tokens", "total_ram_gb", "model_file_size_mb", "n_gpu_layers"]
METRICS = {
    "tps": ("Tokens per second", "tok/s", True),        # (label, unit, higher_is_better)
    "ttft_ms": ("Time to first token", "ms", False),
    "peak_ram_mb": ("Peak RAM", "MB", False),
    "cpu_percent_normalized": ("CPU utilization", "%", False),
    "load_time_s": ("Model load time", "s", False),
}

st.set_page_config(page_title="Local LLM Telemetry", page_icon="📊", layout="wide")


# ---------------------------------------------------------
# Data loading
# ---------------------------------------------------------
@st.cache_data
def read_csv_files(paths: tuple) -> pd.DataFrame:
    frames = []
    for p in paths:
        try:
            df = pd.read_csv(p)
            df["source_file"] = os.path.basename(p)
            frames.append(df)
        except Exception as e:  # skip broken files, report them
            st.warning(f"Could not read {p}: {e}")
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def prepare(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for c in NUMERIC_COLS:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    if "status" in df.columns:
        df = df[df["status"].fillna("ok") == "ok"]
    for col in ["machine_label", "model_name"]:
        df[col] = df[col].fillna("unknown").astype(str) if col in df.columns else "unknown"
    for col in ["tps", "ttft_ms"]:
        if col not in df.columns:
            df[col] = float("nan")
    if "n_gpu_layers" in df.columns:
        df["backend"] = df["n_gpu_layers"].apply(lambda x: "CPU only" if x == 0 else "GPU offload")
    else:
        df["backend"] = "unknown"
    df["config"] = df["machine_label"] + " · " + df["model_name"] + " · " + df["backend"]
    return df.dropna(subset=["tps", "ttft_ms"], how="all")


local_files = tuple(sorted(glob.glob(os.path.join(RESULTS_DIR, "*.csv"))))

with st.sidebar:
    st.header("Data")
    uploads = st.file_uploader("Upload teammates' CSV files", type="csv", accept_multiple_files=True)
    st.caption(f"Also reading {len(local_files)} file(s) from `./{RESULTS_DIR}/`.")

frames = []
if local_files:
    frames.append(read_csv_files(local_files))
for up in uploads or []:
    d = pd.read_csv(up)
    d["source_file"] = up.name
    frames.append(d)

raw = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
using_demo = False
if raw.empty and os.path.exists(DEMO_FILE):
    raw = read_csv_files((DEMO_FILE,))
    using_demo = True

data = prepare(raw) if not raw.empty else pd.DataFrame()

# ---------------------------------------------------------
# Header
# ---------------------------------------------------------
st.title("Local LLM Telemetry Dashboard")
st.caption("Compare on-device LLM performance across machines, operating systems and models.")
if using_demo:
    st.warning("⚠️ No benchmark results found yet — showing **DEMO data** (made-up numbers for layout only). "
               "Run `python benchmark_telemetry.py` or upload CSVs in the sidebar to see real results.")

tab_overview, tab_compare, tab_raw, tab_guide = st.tabs(
    ["Overview", "Compare", "Raw data", "How to Download a Local LLM"])

# ---------------------------------------------------------
# Filters (sidebar) — only when there is data
# ---------------------------------------------------------
if not data.empty:
    with st.sidebar:
        st.header("Filters")

        def multiselect(label, col):
            opts = sorted(data[col].dropna().astype(str).unique())
            return st.multiselect(label, opts, default=opts)

        f_os = multiselect("Operating system", "os") if "os" in data.columns else None
        f_machine = multiselect("Machine", "machine_label")
        f_model = multiselect("Model", "model_name")
        f_backend = multiselect("Backend", "backend")

    mask = data["machine_label"].isin(f_machine) & data["model_name"].isin(f_model) & data["backend"].isin(f_backend)
    if f_os is not None:
        mask &= data["os"].astype(str).isin(f_os)
    view = data[mask]
else:
    view = data


def summary_table(df: pd.DataFrame) -> pd.DataFrame:
    keys = [k for k in ["machine_label", "os", "cpu_model", "total_ram_gb", "model_name", "backend"] if k in df.columns]
    agg = {m: "median" for m in METRICS if m in df.columns}
    out = df.groupby(keys, dropna=False).agg(agg)
    out["runs"] = df.groupby(keys, dropna=False).size()
    return out.reset_index().sort_values("tps", ascending=False)


def no_data_message():
    st.info("No data to show. Run the benchmark or upload CSV files in the sidebar, "
            "and check that your filters aren't excluding everything.")


# ---------------------------------------------------------
# Overview
# ---------------------------------------------------------
with tab_overview:
    if view.empty:
        no_data_message()
    else:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Runs", len(view))
        c2.metric("Machines", view["machine_label"].nunique())
        c3.metric("Models", view["model_name"].nunique())
        best = view.groupby("config")["tps"].median().sort_values(ascending=False)
        c4.metric("Fastest median TPS", f"{best.iloc[0]:.1f} tok/s" if not best.empty else "—")
        if not best.empty:
            st.caption(f"Fastest setup: **{best.index[0]}**")

        st.subheader("Median results per machine × model")
        st.caption("Medians are used so one unusually slow or fast run doesn't distort the comparison.")
        st.dataframe(
            summary_table(view),
            width="stretch", hide_index=True,
            column_config={
                "machine_label": "Machine", "os": "OS", "cpu_model": "CPU", "total_ram_gb": "RAM (GB)",
                "model_name": "Model", "backend": "Backend",
                "tps": st.column_config.NumberColumn("TPS (tok/s)", format="%.1f"),
                "ttft_ms": st.column_config.NumberColumn("TTFT (ms)", format="%.0f"),
                "peak_ram_mb": st.column_config.NumberColumn("Peak RAM (MB)", format="%.0f"),
                "cpu_percent_normalized": st.column_config.NumberColumn("CPU (%)", format="%.1f"),
                "load_time_s": st.column_config.NumberColumn("Load (s)", format="%.2f"),
                "runs": "Runs",
            },
        )

# ---------------------------------------------------------
# Compare
# ---------------------------------------------------------
with tab_compare:
    if view.empty:
        no_data_message()
    else:
        metric = st.radio("Metric", list(METRICS), horizontal=True,
                          format_func=lambda m: f"{METRICS[m][0]} ({METRICS[m][1]})")
        label, unit, higher_better = METRICS[metric]
        st.caption(("Higher" if higher_better else "Lower") + " is better. Bars show the median; dots are individual runs.")

        group_by = st.selectbox("Group bars by", ["config", "machine_label", "model_name", "os"],
                                format_func={"config": "Machine · Model · Backend", "machine_label": "Machine",
                                             "model_name": "Model", "os": "Operating system"}.get)
        plot_df = view.dropna(subset=[metric])
        order = (plot_df.groupby(group_by)[metric].median()
                 .sort_values(ascending=not higher_better).index.tolist())

        bars = alt.Chart(plot_df).mark_bar(opacity=0.85).encode(
            y=alt.Y(f"{group_by}:N", sort=order, title=None),
            x=alt.X(f"median({metric}):Q", title=f"{label} ({unit})"),
            color=alt.Color("model_name:N", title="Model"),
            tooltip=[alt.Tooltip(f"{group_by}:N"), alt.Tooltip(f"median({metric}):Q", format=".1f", title="Median"),
                     alt.Tooltip("count():Q", title="Runs")],
        )
        dots = alt.Chart(plot_df).mark_circle(size=40, color="black", opacity=0.5).encode(
            y=alt.Y(f"{group_by}:N", sort=order), x=f"{metric}:Q",
            tooltip=["machine_label", "model_name", "run_index", alt.Tooltip(f"{metric}:Q", format=".1f")],
        )
        height = max(220, 38 * len(order))
        st.altair_chart((bars + dots).properties(height=height), width="stretch")

        st.subheader("Speed vs. memory trade-off")
        st.caption("Top-left is ideal: fast generation with low memory use.")
        scatter_src = view.dropna(subset=["tps", "peak_ram_mb"])
        scatter_src = scatter_src.groupby(["config", "machine_label", "model_name"], as_index=False)[
            ["tps", "peak_ram_mb", "ttft_ms"]].median()
        scatter = alt.Chart(scatter_src).mark_circle(size=160).encode(
            x=alt.X("peak_ram_mb:Q", title="Peak RAM (MB)"),
            y=alt.Y("tps:Q", title="Tokens per second"),
            color=alt.Color("machine_label:N", title="Machine"),
            shape=alt.Shape("model_name:N", title="Model"),
            tooltip=["machine_label", "model_name", alt.Tooltip("tps:Q", format=".1f"),
                     alt.Tooltip("peak_ram_mb:Q", format=".0f"), alt.Tooltip("ttft_ms:Q", format=".0f")],
        ).properties(height=380)
        st.altair_chart(scatter, width="stretch")

# ---------------------------------------------------------
# Raw data
# ---------------------------------------------------------
with tab_raw:
    if view.empty:
        no_data_message()
    else:
        st.dataframe(view, width="stretch", hide_index=True)
        st.download_button("Download filtered data (CSV)", view.to_csv(index=False).encode("utf-8"),
                           file_name="telemetry_filtered.csv", mime="text/csv")

# ---------------------------------------------------------
# Guide: how to download a local LLM
# ---------------------------------------------------------
with tab_guide:
    st.header("How to Download a Local LLM")
    st.markdown("""
You can download open-weight models directly from websites by clicking a download button.
For this project, **download a GGUF file** — it's already quantized (compressed) and comes as a
single file that `llama-cpp-python` can run on a normal laptop.

---

### Option 1 — Hugging Face (huggingface.co)

Hugging Face is the main platform for downloading models. Almost every open-weight model is published here.

1. Go to **[huggingface.co](https://huggingface.co)** and search for the model name,
   for example `Llama-3.1-8B-Instruct-GGUF`.
2. Open the model page and click the **"Files and versions"** tab.
3. Click the **download icon** next to the file you want.

**Which file should I pick?**
- For running locally, choose a **GGUF** file (already quantized, single file).
  A `Q4_K_M` version is a good balance of size and quality for laptops.
- The official original releases come as several `.safetensors` files and are much larger —
  you don't need those for this project.

> **Note:** The official repositories from **Meta** and **Google** require you to **log in and accept
> the license** first. You can download only after your request is approved.

---

### Option 2 — Kaggle (kaggle.com/models)

Google's **Gemma** and Meta's **Llama** models are also published on **[Kaggle Models](https://www.kaggle.com/models)**.

1. Sign in to Kaggle.
2. Open the model page and **accept the license**.
3. Download the model files.

---

### Option 3 — Official websites

- **Meta (Llama):** go to **[llama.com](https://www.llama.com)** and fill in the request form.
  Meta then sends you a **download link that expires after a limited time**, so use it soon.
- **Mistral:** Mistral's **official documentation** provides download links for its open models.

---

### After downloading — use it with this project

1. Create a `models` folder inside the project (if it doesn't exist) and move the `.gguf` file into it.
2. Run the benchmark, pointing it to your file:
   ```bash
   python benchmark_telemetry.py --model ./models/YOUR_MODEL.gguf --runs 3 --tester YOUR_NAME --machine-label "YOUR-LAPTOP"
   ```
3. Refresh this dashboard — your results appear automatically from the `results/` folder.
   To compare with teammates, upload their CSV files in the sidebar.

**Tip:** Check your free RAM before downloading. A model needs roughly its file size in RAM, plus extra
for the context — e.g. a 4.9 GB file needs around 6 GB of free memory.
""")
