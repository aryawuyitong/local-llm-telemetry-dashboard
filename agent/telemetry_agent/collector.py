"""Benchmark collector: measures TTFT, TPS, CPU %, and peak RAM for a local model.

Run it directly:
    python -m telemetry_agent bench --model qwen2.5:1.5b --tester Rohan

Method (keep it the same for every machine so results compare fairly):
  * 1 warm-up request (loads the model; its time is reported as load_time_s)
  * then each standard prompt x `repeats`, streamed, temperature 0, max 128 tokens
    (each run gets a unique tag so the runtime can't reuse a cached prompt)
  * TTFT = request sent -> first text chunk received
  * TPS  = (output tokens - 1) / (last chunk time - first chunk time)
  * CPU  = summed CPU % of the runtime's processes, divided by logical cores (0-100 % of the machine)
  * RAM  = peak summed resident memory (RSS) of the runtime's processes during the request
Writes results/<run>.json and appends one row per run to results/runs.csv
(the column names match the team dashboard).
"""
from __future__ import annotations

import csv
import json
import os
import statistics
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import psutil

from .config import Settings
from .llm import ChatClient
from .system import hardware_info

PROMPTS = {
    "short": "In one sentence, what does a CPU do?",
    "medium": "In about 80 words, explain why a quantized model uses less memory than the original.",
    "long": (
        "Read this note and summarize it in exactly 3 bullet points.\n\n"
        "Running a language model locally means the model's weights live on your own laptop. "
        "A runtime such as llama.cpp or Ollama loads the GGUF file into memory, splits your prompt "
        "into tokens, and predicts the answer one token at a time. The first token takes longest "
        "because the whole prompt has to be processed first; after that, tokens stream out at a "
        "steady speed that depends on the model's size, its quantization, and whether a GPU helps. "
        "Bigger models usually give better answers but need more RAM and generate fewer tokens per "
        "second. Because nothing leaves the laptop, local models work offline and keep data private, "
        "but they are limited by the hardware you have."
    ),
}

# Newer Ollama versions do inference in a child "llama-server" process, so watch both names.
RUNTIME_PROCESS_HINTS = {
    "ollama": ("ollama", "llama-server"),
    "llama.cpp": ("llama-server", "llama-cli"),
}

CSV_FIELDS = ["machine_label", "tester", "os", "os_version", "cpu_model", "model_name", "runtime",
              "total_ram_gb", "n_gpu_layers", "prompt_id", "run_index", "load_time_s", "ttft_ms",
              "tps", "output_tokens", "cpu_percent_normalized", "peak_ram_mb", "timestamp"]


def runtime_processes(runtime: str) -> list[psutil.Process]:
    hints = RUNTIME_PROCESS_HINTS.get(runtime, ("ollama", "llama"))
    procs = []
    for p in psutil.process_iter(["name"]):
        name = (p.info.get("name") or "").lower()
        if any(h in name for h in hints):
            procs.append(p)
    return procs


class ResourceSampler:
    """Samples CPU and RSS of the runtime processes in a background thread."""

    def __init__(self, procs: list[psutil.Process], interval: float = 0.1):
        self.procs = procs
        self.interval = interval
        self.cpu_samples: list[float] = []
        self.peak_rss = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self.cores = psutil.cpu_count(logical=True) or 1

    def _sample(self, prime: bool = False):
        cpu, rss = 0.0, 0
        for p in self.procs:
            try:
                cpu += p.cpu_percent(None)
                rss += p.memory_info().rss
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        if not prime:
            self.cpu_samples.append(cpu / self.cores)
        self.peak_rss = max(self.peak_rss, rss)

    def _run(self):
        self._sample(prime=True)  # first cpu_percent call only sets a baseline
        while not self._stop.wait(self.interval):
            self._sample()

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._thread.join()


def measure_once(client: ChatClient, prompt: str, runtime: str, max_tokens: int = 128) -> dict:
    procs = runtime_processes(runtime)
    # Runtimes cache an identical prompt, which makes repeat TTFTs unrealistically fast.
    # A unique tag at the start forces the whole prompt to be processed every run.
    prompt = f"[run {uuid.uuid4().hex[:6]}] {prompt}"
    with ResourceSampler(procs) as sampler:
        t0 = time.perf_counter()
        first = last = None
        chunks, usage = 0, None
        for ts, delta, u in client.stream([{"role": "user", "content": prompt}], max_tokens=max_tokens):
            if u:
                usage = u
            if delta:
                chunks += 1
                first = first or ts
                last = ts
    if first is None:
        raise RuntimeError("The model returned no text.")
    tokens = (usage or {}).get("completion_tokens") or chunks
    gen_time = (last - first) if last and last > first else None
    return {
        "ttft_ms": round((first - t0) * 1000, 1),
        "tps": round((tokens - 1) / gen_time, 2) if gen_time and tokens > 1 else None,
        "output_tokens": tokens,
        "cpu_percent_normalized": round(statistics.mean(sampler.cpu_samples), 1) if sampler.cpu_samples else None,
        "peak_ram_mb": round(sampler.peak_rss / 1024 ** 2, 1) if sampler.peak_rss else None,
        "processes_found": len(procs),
    }


def _median(rows: list[dict], key: str):
    vals = [r[key] for r in rows if r.get(key) is not None]
    return round(statistics.median(vals), 2) if vals else None


def run_benchmark(model: str, settings: Settings, repeats: int = 1,
                  prompt_ids: list[str] | None = None, tester: str = "",
                  machine_label: str | None = None) -> dict:
    client = ChatClient(settings.base_url, model)
    hw = hardware_info(settings.models_dir)
    prompt_ids = prompt_ids or list(PROMPTS)

    t = time.perf_counter()
    client.chat([{"role": "user", "content": "Reply with the word ready."}], max_tokens=5)
    load_time_s = round(time.perf_counter() - t, 2)

    label = machine_label or os.environ.get("MACHINE_LABEL") or f"{hw['os']}-{hw['cpu_model']}"
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = []
    for pid in prompt_ids:
        for i in range(1, repeats + 1):
            m = measure_once(client, PROMPTS[pid], settings.runtime)
            rows.append({
                "machine_label": label, "tester": tester, "os": hw["os"], "os_version": hw["os_version"],
                "cpu_model": hw["cpu_model"], "model_name": model, "runtime": settings.runtime,
                "total_ram_gb": hw["total_ram_gb"], "n_gpu_layers": os.environ.get("N_GPU_LAYERS", ""),
                "prompt_id": pid, "run_index": i, "load_time_s": load_time_s,
                "timestamp": stamp, **{k: v for k, v in m.items() if k != "processes_found"},
            })

    summary = {
        "model": model, "runtime": settings.runtime, "machine_label": label,
        "runs": len(rows), "load_time_s": load_time_s,
        "median_ttft_ms": _median(rows, "ttft_ms"), "median_tps": _median(rows, "tps"),
        "median_cpu_percent": _median(rows, "cpu_percent_normalized"),
        "peak_ram_mb": max((r["peak_ram_mb"] or 0) for r in rows) or None,
        "note": ("CPU % can look low on Apple Silicon because the GPU does most of the work."
                 if "Apple" in hw["gpu"] else ""),
    }
    out = _save(settings.results_dir, rows, summary, hw)
    summary["saved_to"] = str(out)
    return summary


def _save(results_dir: Path, rows: list[dict], summary: dict, hw: dict) -> Path:
    results_dir.mkdir(parents=True, exist_ok=True)
    safe = "".join(c if c.isalnum() or c in "-_." else "-" for c in f"{summary['machine_label']}_{summary['model']}")
    path = results_dir / f"{datetime.now().strftime('%Y%m%d-%H%M%S')}_{safe}.json"
    path.write_text(json.dumps({"summary": summary, "hardware": hw, "runs": rows}, indent=2))
    csv_path = results_dir / "runs.csv"
    new = not csv_path.exists()
    with csv_path.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        if new:
            w.writeheader()
        w.writerows(rows)
    return path
