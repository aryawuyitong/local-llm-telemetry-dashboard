"""
Local LLM telemetry benchmark.

Runs a GGUF model with llama-cpp-python, measures operational telemetry
(load time, TTFT, TPS, CPU, RAM) and appends one row per run to a CSV file
so results from different machines and models can be compared in the
Streamlit dashboard (app.py).

Example:
    python benchmark_telemetry.py --model ./models/qwen1_5-1_8b-chat-q4_k_m.gguf --runs 3 --tester gloria
"""

import argparse
import csv
import os
import platform
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone

import psutil
from llama_cpp import Llama

try:
    import llama_cpp
    LLAMA_CPP_VERSION = getattr(llama_cpp, "__version__", "unknown")
except Exception:  # pragma: no cover
    LLAMA_CPP_VERSION = "unknown"

# ---------------------------------------------------------
# Defaults
# ---------------------------------------------------------
DEFAULT_MODEL_PATH = "./models/qwen1_5-1_8b-chat-q4_k_m.gguf"
DEFAULT_PROMPT = "Explain the fundamental difference between TCP and UDP protocols in one short paragraph."
DEFAULT_OUTPUT = "./results/benchmarks.csv"

CSV_COLUMNS = [
    "timestamp_utc", "session_id", "run_index", "tester", "machine_label",
    "os", "os_version", "arch", "cpu_model", "physical_cores", "logical_cores", "total_ram_gb",
    "model_name", "model_file_size_mb", "n_ctx", "n_gpu_layers", "n_threads", "max_tokens", "prompt",
    "load_time_s", "ttft_ms", "tps", "output_tokens", "total_time_s",
    "cpu_percent_raw", "cpu_percent_normalized", "baseline_ram_mb", "peak_ram_mb",
    "llama_cpp_version", "status",
]


# ---------------------------------------------------------
# Machine info
# ---------------------------------------------------------
def get_cpu_model() -> str:
    """Best-effort human-readable CPU name on Windows, macOS and Linux."""
    system = platform.system()
    try:
        if system == "Darwin":
            out = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"],
                                 capture_output=True, text=True, timeout=5)
            if out.stdout.strip():
                return out.stdout.strip()
        elif system == "Linux":
            with open("/proc/cpuinfo", encoding="utf-8") as f:
                for line in f:
                    if line.lower().startswith("model name"):
                        return line.split(":", 1)[1].strip()
        elif system == "Windows":
            out = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "(Get-CimInstance Win32_Processor).Name"],
                capture_output=True, text=True, timeout=10)
            if out.stdout.strip():
                return out.stdout.strip().splitlines()[0]
    except Exception:
        pass
    return platform.processor() or "unknown"


def get_machine_info() -> dict:
    system = platform.system()
    os_version = platform.mac_ver()[0] if system == "Darwin" else platform.release()
    return {
        "os": {"Darwin": "macOS"}.get(system, system),
        "os_version": os_version,
        "arch": platform.machine(),
        "cpu_model": get_cpu_model(),
        "physical_cores": psutil.cpu_count(logical=False),
        "logical_cores": psutil.cpu_count(logical=True),
        "total_ram_gb": round(psutil.virtual_memory().total / (1024 ** 3), 1),
    }


# ---------------------------------------------------------
# Peak RAM sampler
# ---------------------------------------------------------
class PeakRamSampler:
    """Samples process RSS in a background thread to capture the real peak,
    not just the value at the end of generation."""

    def __init__(self, process: psutil.Process, interval_s: float = 0.05):
        self.process = process
        self.interval_s = interval_s
        self.peak_bytes = process.memory_info().rss
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        while not self._stop.is_set():
            try:
                self.peak_bytes = max(self.peak_bytes, self.process.memory_info().rss)
            except psutil.Error:
                break
            self._stop.wait(self.interval_s)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._thread.join()
        # one last sample in case the peak happened right at the end
        self.peak_bytes = max(self.peak_bytes, self.process.memory_info().rss)

    @property
    def peak_mb(self) -> float:
        return self.peak_bytes / (1024 * 1024)


# ---------------------------------------------------------
# One benchmark run
# ---------------------------------------------------------
def run_once(llm: Llama, prompt: str, max_tokens: int, show_output: bool) -> dict:
    process = psutil.Process()
    baseline_ram_mb = process.memory_info().rss / (1024 * 1024)

    process.cpu_percent()  # reset the CPU counter right before generation
    start_time = time.perf_counter()
    first_token_time = None
    token_count = 0

    with PeakRamSampler(process) as sampler:
        # Streaming lets us capture the exact moment the first token arrives (TTFT)
        for output in llm(prompt, max_tokens=max_tokens, stream=True):
            if first_token_time is None:
                first_token_time = time.perf_counter()
            token_count += 1  # each streamed chunk is one generated token
            if show_output:
                print(output["choices"][0]["text"], end="", flush=True)
        end_time = time.perf_counter()

    cpu_raw = process.cpu_percent()  # % since reset; can exceed 100 on multi-core
    logical = psutil.cpu_count(logical=True) or 1

    if first_token_time is None:  # model produced nothing
        ttft_ms, tps, status = None, None, "no_tokens"
    else:
        ttft_ms = (first_token_time - start_time) * 1000
        # TPS excludes prompt processing (prefill): first token -> last token
        gen_duration = end_time - first_token_time
        tps = (token_count - 1) / gen_duration if gen_duration > 0 and token_count > 1 else None
        status = "ok"

    return {
        "ttft_ms": round(ttft_ms, 2) if ttft_ms is not None else None,
        "tps": round(tps, 2) if tps is not None else None,
        "output_tokens": token_count,
        "total_time_s": round(end_time - start_time, 3),
        "cpu_percent_raw": round(cpu_raw, 1),
        "cpu_percent_normalized": round(cpu_raw / logical, 1),
        "baseline_ram_mb": round(baseline_ram_mb, 1),
        "peak_ram_mb": round(sampler.peak_mb, 1),
        "status": status,
    }


def append_rows(path: str, rows: list) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    is_new = not os.path.exists(path) or os.path.getsize(path) == 0
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        if is_new:
            writer.writeheader()
        writer.writerows(rows)


def parse_args():
    p = argparse.ArgumentParser(description="Benchmark a local GGUF model and log telemetry to CSV.")
    p.add_argument("--model", default=DEFAULT_MODEL_PATH, help="Path to the .gguf model file")
    p.add_argument("--prompt", default=DEFAULT_PROMPT)
    p.add_argument("--runs", type=int, default=3, help="Number of measured runs (default 3)")
    p.add_argument("--warmup", type=int, default=1, help="Unrecorded warm-up runs (default 1)")
    p.add_argument("--max-tokens", type=int, default=256)
    p.add_argument("--n-ctx", type=int, default=2048)
    p.add_argument("--n-gpu-layers", type=int, default=0,
                   help="0 = CPU only (baseline). -1 = offload all layers (e.g. Metal on macOS)")
    p.add_argument("--n-threads", type=int, default=None, help="CPU threads (default: llama.cpp decides)")
    p.add_argument("--tester", default=os.environ.get("USER") or os.environ.get("USERNAME") or "unknown",
                   help="Your name, so the team knows who ran it")
    p.add_argument("--machine-label", default=platform.node(),
                   help="Friendly machine name, e.g. 'Gloria-MacBookAir-M2'")
    p.add_argument("--output", default=DEFAULT_OUTPUT, help="CSV file to append results to")
    p.add_argument("--quiet", action="store_true", help="Don't print the model's generated text")
    return p.parse_args()


def main():
    args = parse_args()
    if not os.path.isfile(args.model):
        raise SystemExit(f"Model file not found: {args.model}\n"
                         "Download a GGUF model first (see the 'How to Download a Local LLM' tab in the dashboard).")

    machine = get_machine_info()
    print(f"Machine: {args.machine_label} | {machine['os']} {machine['os_version']} | "
          f"{machine['cpu_model']} | {machine['total_ram_gb']} GB RAM")

    print("Loading model...")
    load_start = time.perf_counter()
    llm = Llama(
        model_path=args.model,
        n_ctx=args.n_ctx,
        n_gpu_layers=args.n_gpu_layers,
        n_threads=args.n_threads,
        verbose=False,
    )
    load_time_s = time.perf_counter() - load_start
    print(f"Model loaded in {load_time_s:.2f} s")

    for i in range(args.warmup):
        print(f"Warm-up run {i + 1}/{args.warmup} (not recorded)...")
        run_once(llm, args.prompt, args.max_tokens, show_output=False)

    session_id = uuid.uuid4().hex[:8]
    rows = []
    for i in range(1, args.runs + 1):
        print(f"\n=== Run {i}/{args.runs} ===")
        if not args.quiet:
            print("-" * 50)
        result = run_once(llm, args.prompt, args.max_tokens, show_output=not args.quiet)
        if not args.quiet:
            print("\n" + "-" * 50)
        print(f"TTFT: {result['ttft_ms']} ms | TPS: {result['tps']} tok/s | "
              f"CPU: {result['cpu_percent_normalized']}% | Peak RAM: {result['peak_ram_mb']} MB")

        rows.append({
            "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "session_id": session_id,
            "run_index": i,
            "tester": args.tester,
            "machine_label": args.machine_label,
            **machine,
            "model_name": os.path.basename(args.model),
            "model_file_size_mb": round(os.path.getsize(args.model) / (1024 * 1024), 1),
            "n_ctx": args.n_ctx,
            "n_gpu_layers": args.n_gpu_layers,
            "n_threads": args.n_threads if args.n_threads is not None else "auto",
            "max_tokens": args.max_tokens,
            "prompt": args.prompt,
            "load_time_s": round(load_time_s, 3),
            "llama_cpp_version": LLAMA_CPP_VERSION,
            **result,
        })

    append_rows(args.output, rows)
    print(f"\nSaved {len(rows)} run(s) to {args.output}")
    print("Open the dashboard with:  streamlit run app.py")


if __name__ == "__main__":
    main()
