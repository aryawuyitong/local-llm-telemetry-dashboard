"""Reproducible local benchmark and anonymous session export.

Protocol local-llm-lab/1: a warm-up, then three prompts x three repeats.
TTFT is client first-text latency. Decode TPS is Ollama eval_count divided by
its eval_duration in seconds (https://docs.ollama.com/api/chat). Text chunks
are never token counts. CPU/RSS are attributed to the endpoint listener and
its refreshed child process tree; unknown attribution produces null metrics.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import shutil
import statistics
import subprocess
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import psutil

from .config import Settings, load_allow_list
from .llm import ChatClient, LLMError
from .protocol import METRICS, PROTOCOL_VERSION, SCHEMA_VERSION, safe_alias, summarize_runs, validate_session
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
        "second. Because inference runs on the laptop, an appropriately configured runtime can work "
        "offline after setup, but it is limited by the hardware you have."
    ),
}
CONTEXT_TOKENS = 2048
SAMPLE_INTERVAL_S = 0.1
_CACHE_POLICY = "unique_prefix_per_run_cache_not_guaranteed_disabled"
_BENCHMARK_LOCK = threading.Lock()
CSV_FIELDS = ["machine_label", "os", "os_version", "cpu_model", "model_name", "runtime",
              "total_ram_gb", "prompt_id", "run_index", "warmup_round_trip_s", "ttft_ms", "tps",
              "output_tokens", "cpu_percent_normalized", "peak_ram_mb", "timestamp", "status"]


def utc_stamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def runtime_processes(runtime: str = "ollama", base_url: str | None = None) -> list[psutil.Process]:
    """Find the local TCP listener, not every process with a runtime-like name.

    macOS may deny the global connection table for a standard user; fixed argv
    lsof is a read-only fallback. Failure to verify a listener is explicit, never
    replaced by matching unrelated process names or this Python collector.
    """
    if not base_url:
        return []
    address = urlsplit(base_url)
    port = address.port or 80
    pids = set()
    try:
        accepted_addresses = {address.hostname, "0.0.0.0" if address.hostname == "127.0.0.1" else "::"}
        for conn in psutil.net_connections(kind="tcp"):
            if (conn.status == psutil.CONN_LISTEN and conn.laddr and conn.laddr.port == port
                    and conn.laddr.ip in accepted_addresses and conn.pid):
                pids.add(conn.pid)
    except (psutil.AccessDenied, OSError, NotImplementedError):
        pass
    if not pids:
        executable = shutil.which("lsof")
        if executable:
            try:
                result = subprocess.run([executable, "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-Fpn"],
                                        capture_output=True, text=True, timeout=3, check=False)
                candidate = None
                allowed = {f"127.0.0.1:{port}", f"*:{port}"} if address.hostname == "127.0.0.1" else {f"[::1]:{port}", f"*:{port}"}
                for line in result.stdout.splitlines():
                    if line.startswith("p") and line[1:].isdigit():
                        candidate = int(line[1:])
                    elif line.startswith("n") and line[1:] in allowed and candidate:
                        pids.add(candidate)
            except (OSError, subprocess.SubprocessError):
                pass
    roots = []
    for pid in pids:
        try:
            roots.append(psutil.Process(pid))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return roots


class ResourceSampler:
    """Refresh listener roots periodically and child processes on every sample."""
    def __init__(self, procs=None, interval: float = SAMPLE_INTERVAL_S, process_provider=None):
        self.interval = interval
        self.process_provider = process_provider or (lambda: procs or [])
        self.cpu_samples: list[float] = []
        self.peak_rss: int | None = None
        self.process_count = 0
        self.attribution_complete = True
        self.flags: set[str] = set()
        self.cores = psutil.cpu_count(logical=True) or 1
        self._roots = []
        self._last_refresh = float("-inf")
        self._previous = {}
        self._previous_time = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _sample(self):
        now = time.perf_counter()
        if now - self._last_refresh >= 1 or not self._roots:
            try:
                self._roots = self.process_provider()
            except (psutil.Error, OSError):
                self._roots = []
                self.flags.add("process_discovery_failed")
            self._last_refresh = now
        processes = {}
        for root in self._roots:
            try:
                processes[root.pid] = root
                for child in root.children(recursive=True):
                    processes[child.pid] = child
            except psutil.AccessDenied:
                self.flags.add("process_access_denied")
                self.attribution_complete = False
            except OSError:
                self.flags.add("child_process_discovery_unavailable")
                self.attribution_complete = False
            except psutil.NoSuchProcess:
                continue
        rss, current, cpu_delta, cpu_matches = 0, {}, 0.0, 0
        for pid, proc in processes.items():
            try:
                # Creation time distinguishes PID reuse; CPU times avoid the invalid
                # first cpu_percent() sample when a new child appears mid-request.
                ident = (pid, proc.create_time())
                times = proc.cpu_times()
                current[ident] = times.user + times.system
                rss += proc.memory_info().rss
                if ident in self._previous:
                    cpu_delta += max(0.0, current[ident] - self._previous[ident])
                    cpu_matches += 1
            except (psutil.AccessDenied, OSError):
                self.flags.add("process_access_denied")
                self.attribution_complete = False
            except psutil.NoSuchProcess:
                self.flags.add("process_exited_during_sample")
        self.process_count = max(self.process_count, len(current))
        if current:
            self.peak_rss = max(self.peak_rss or 0, rss)
        if cpu_matches and self._previous_time is not None and now > self._previous_time:
            sample = 100 * cpu_delta / (now - self._previous_time) / self.cores
            if sample > 100:
                self.flags.add("cpu_sample_clamped")
            self.cpu_samples.append(min(100.0, max(0.0, sample)))
        self._previous, self._previous_time = current, now

    def _run(self):
        while not self._stop.wait(self.interval):
            self._sample()

    def __enter__(self):
        self._sample()
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._thread.join(timeout=5)
        # Capture short requests and the final memory observation as well.
        self._sample()


def _finite(value, *, positive=False, integer=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        if not math.isfinite(value):
            return None
    except OverflowError:
        return None
    if value < 0 or (positive and value == 0) or (integer and not isinstance(value, int)):
        return None
    return value


def measure_once(client: ChatClient, prompt: str, runtime: str, max_tokens: int = 128,
                 context_tokens: int = CONTEXT_TOKENS) -> dict:
    """Measure one request, retaining missing/error state rather than fabricating data."""
    tagged = f"[run {uuid.uuid4().hex[:12]}] {prompt}"
    flags, usage, first, failure = set(), {}, None, None
    provider = lambda: runtime_processes(runtime, getattr(client, "base_url", None))
    sampler = ResourceSampler(process_provider=provider)
    t0 = None
    try:
        with sampler:
            t0 = time.perf_counter()
            stream = (client.benchmark_stream([{"role": "user", "content": tagged}], runtime=runtime,
                                             max_tokens=max_tokens, temperature=0, context_tokens=context_tokens)
                      if hasattr(client, "benchmark_stream") else
                      client.stream([{"role": "user", "content": tagged}], max_tokens=max_tokens, temperature=0))
            for timestamp, delta, record in stream:
                if isinstance(record, dict):
                    usage = record
                if delta and first is None:
                    first = timestamp
    except (LLMError, OSError, ValueError, TimeoutError):
        failure = "The local benchmark request failed or was interrupted; retry after checking the runtime."
        flags.add("inference_failed")
    tokens = _finite(usage.get("eval_count"), integer=True)
    if tokens is not None and tokens > max_tokens:
        tokens = None
        flags.add("token_count_out_of_bounds")
    duration_ns = _finite(usage.get("eval_duration"), positive=True)
    native = usage.get("source") == "ollama_native"
    duration_s = duration_ns / 1e9 if duration_ns is not None and native else None
    tps = tokens / duration_s if tokens is not None and duration_s else None
    if tokens is None and "token_count_out_of_bounds" not in flags:
        # Completion counts can still be reported, but never chunk-count fallback.
        tokens = _finite(usage.get("completion_tokens"), integer=True)
        if tokens is not None and tokens > max_tokens:
            tokens = None
            flags.add("token_count_out_of_bounds")
    if tps is None:
        flags.add("decode_timing_unavailable")
    if first is None:
        flags.add("first_text_unavailable")
        failure = failure or "The local model returned no response text."
    flags.update(sampler.flags)
    if not sampler.process_count:
        flags.add("process_attribution_unavailable")
    if not sampler.cpu_samples:
        flags.add("cpu_samples_unavailable")
    if sampler.peak_rss is None:
        flags.add("rss_samples_unavailable")
    attributed = sampler.process_count > 0 and getattr(sampler, "attribution_complete", True)
    if not attributed:
        flags.add("process_attribution_unavailable")
    measurements = {
        "ttft_ms": round((first - t0) * 1000, 3) if first is not None and t0 is not None and first >= t0 else None,
        "decode_tps": round(tps, 3) if tps is not None else None,
        "cpu_percent_normalized": round(statistics.mean(sampler.cpu_samples), 3) if attributed and sampler.cpu_samples else None,
        "peak_rss_mib": round(sampler.peak_rss / 1024**2, 3) if attributed and sampler.peak_rss is not None else None,
    }
    sources = {
        "ttft_ms": "client_monotonic_first_nonempty_text" if measurements["ttft_ms"] is not None else None,
        "decode_tps": "ollama.eval_count/eval_duration_ns" if measurements["decode_tps"] is not None else None,
        "cpu_percent_normalized": "psutil.process_cpu_times/logical_cores" if measurements["cpu_percent_normalized"] is not None else None,
        "peak_rss_mib": "psutil.sum_runtime_process_rss" if measurements["peak_rss_mib"] is not None else None,
        "output_tokens": tokens, "decode_duration_s": duration_s,
        "sample_interval_s": sampler.interval, "process_count": sampler.process_count,
        "process_attribution": "endpoint_owner_and_children" if attributed else "unavailable",
        "cache_policy": _CACHE_POLICY, "prompt_hash": hashlib.sha256(tagged.encode()).hexdigest(),
    }
    status = "error" if failure else ("partial" if flags or any(v is None for v in measurements.values()) else "ok")
    return {"status": status, "measurements": measurements, "sources": sources,
            "quality_flags": sorted(flags), "error": failure,
            # Compatibility for code that called measure_once directly.
            "ttft_ms": measurements["ttft_ms"], "tps": measurements["decode_tps"], "output_tokens": tokens,
            "cpu_percent_normalized": measurements["cpu_percent_normalized"], "peak_ram_mb": measurements["peak_rss_mib"]}


@contextmanager
def _exclusive_benchmark(results_dir: Path):
    """One benchmark per process AND per results directory, with crash-safe OS locks."""
    if not _BENCHMARK_LOCK.acquire(blocking=False):
        raise RuntimeError("A benchmark is already running. Wait for it to finish.")
    handle = None
    locked = False
    try:
        results_dir.mkdir(parents=True, exist_ok=True)
        handle = (results_dir / ".benchmark.lock").open("a+b")
        if os.name == "nt":
            import msvcrt
            # Windows byte-range locks require a byte to exist in the file.
            handle.seek(0, 2)
            if handle.tell() == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise RuntimeError("A benchmark is already running in this results folder.") from exc
        else:
            import fcntl
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise RuntimeError("A benchmark is already running in this results folder.") from exc
        locked = True
        yield
    finally:
        if handle is not None:
            if locked:
                if os.name == "nt":
                    import msvcrt
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()
        _BENCHMARK_LOCK.release()


def _failed_run(prompt: str, reason="Warm-up failed; no measured request was attempted.") -> dict:
    return {"status": "error", "measurements": {key: None for key in METRICS},
            "sources": {**{key: None for key in METRICS}, "output_tokens": None, "decode_duration_s": None,
                        "sample_interval_s": SAMPLE_INTERVAL_S, "process_count": 0,
                        "process_attribution": "unavailable", "cache_policy": _CACHE_POLICY,
                        "prompt_hash": hashlib.sha256(prompt.encode()).hexdigest()},
            "quality_flags": ["warmup_failed"], "error": reason}


def run_benchmark(model: str, settings: Settings, repeats: int = 3,
                  prompt_ids: list[str] | None = None, tester: str = "",
                  machine_label: str | None = None, guess_tps: float | None = None,
                  guess_ram_gb: float | None = None) -> dict:
    """Run a bounded session; return legacy summary keys plus the anonymous export path.

    `tester` is accepted for CLI compatibility and deliberately never exported.
    `machine_label` is an explicit pseudonym, never auto-populated from account or
    hostname. Failed requests remain in the JSON and summary denominators.
    """
    if type(repeats) is not int or not 1 <= repeats <= 3:
        raise ValueError("repeats must be an integer from 1 to 3")
    prompt_ids = list(PROMPTS) if prompt_ids is None else prompt_ids
    if (not isinstance(prompt_ids, list) or not prompt_ids or len(prompt_ids) > 3
            or any(not isinstance(pid, str) or pid not in PROMPTS for pid in prompt_ids)
            or len(set(prompt_ids)) != len(prompt_ids)):
        raise ValueError("Select unique standard prompt IDs: short, medium, long")
    if not isinstance(model, str) or not model or len(model) > 128 or any(c.isspace() for c in model):
        raise ValueError("Invalid benchmark model identifier")
    allowed = {item["ollama_tag"] for item in load_allow_list()}
    if model not in allowed:
        raise ValueError("Only catalog allow-listed model identifiers can be benchmarked")
    for prediction in (guess_tps, guess_ram_gb):
        if prediction is not None and _finite(prediction) is None:
            raise ValueError("Predictions must be finite non-negative numbers")
    session_id = uuid.uuid4().hex
    label = safe_alias(machine_label, session_id)
    with _exclusive_benchmark(settings.results_dir):
        client = ChatClient(settings.base_url, model)
        hw = hardware_info(settings.models_dir)
        metadata = {"runtime_version": None, "model_digest": None, "quantization": None,
                    "acceleration": "unknown", "other_models_resident": False, "context_tokens": None}
        warmup_s, warmup_failed = None, False
        started = time.perf_counter()
        try:
            content_seen = False
            for _, delta, _ in client.benchmark_stream([{"role": "user", "content": "Reply with the word ready."}],
                    runtime=settings.runtime, max_tokens=5, temperature=0, context_tokens=CONTEXT_TOKENS):
                content_seen = content_seen or bool(delta)
            if not content_seen:
                raise LLMError("No warm-up text")
            warmup_s = round(time.perf_counter() - started, 4)
        except (LLMError, OSError, ValueError, TimeoutError):
            warmup_failed = True
        if hasattr(client, "metadata"):
            metadata.update(client.metadata(settings.runtime))
        rows = []
        for pid in prompt_ids:
            for index in range(1, repeats + 1):
                result = _failed_run(PROMPTS[pid]) if warmup_failed else measure_once(client, PROMPTS[pid], settings.runtime)
                row = {"run_id": uuid.uuid4().hex, "prompt_id": pid, "repeat_index": index, "timestamp": utc_stamp(),
                       **{key: result[key] for key in ("status", "measurements", "sources", "quality_flags", "error")}}
                if metadata["other_models_resident"]:
                    row["quality_flags"] = sorted(set(row["quality_flags"]) | {"other_models_resident"})
                    if row["status"] == "ok":
                        row["status"] = "partial"
                if metadata["context_tokens"] not in (None, CONTEXT_TOKENS):
                    row["quality_flags"] = sorted(set(row["quality_flags"]) | {"context_length_mismatch"})
                    if row["status"] == "ok":
                        row["status"] = "partial"
                rows.append(row)
        summary = summarize_runs(rows)
        summary.update({"model": model, "runtime": settings.runtime, "machine_label": label,
                        "warmup_round_trip_s": warmup_s,
                        "note": "CPU excludes GPU work. RSS may double-count shared pages. Background workloads and cache affect results.",
                        "quality_flags": (["warmup_failed"] if warmup_failed else [])
                                         + (["runtime_version_unavailable"] if metadata["runtime_version"] is None else [])
                                         + (["model_digest_unavailable"] if metadata["model_digest"] is None else [])})
        if metadata["context_tokens"] is None:
            summary["quality_flags"].append("context_length_not_verified")
        session = {"schema_version": SCHEMA_VERSION, "protocol_version": PROTOCOL_VERSION, "data_kind": "measured",
                   "session_id": session_id, "created_at": utc_stamp(),
                   "device": {"alias": label, "os": hw["os"], "os_version": hw["os_version"] or "unknown",
                              "cpu_model": hw["cpu_model"] or "unknown", "logical_cores": hw.get("cpu_cores_logical") or 1,
                              "total_ram_gib": hw["total_ram_gb"], "gpu": hw.get("gpu") or "unknown", "arch": hw["arch"]},
                   "runtime": {"name": settings.runtime, "version": metadata["runtime_version"]},
                   "model": {"name": model, "digest": metadata["model_digest"], "quantization": metadata["quantization"],
                             "acceleration": metadata["acceleration"]},
                   "config": {"temperature": 0, "max_output_tokens": 128, "repeats": repeats, "context_tokens": CONTEXT_TOKENS},
                   "warmup_round_trip_s": warmup_s, "predictions": {"tps": guess_tps, "ram_gib": guess_ram_gb},
                   "runs": rows, "summary": summary}
        validate_session(session)
        out = _save(settings.results_dir, session)
        return {**summary, "session_id": session_id, "saved_to": str(out), "data_kind": "measured"}


def _save(results_dir: Path, session: dict) -> Path:
    """Atomic anonymous JSON plus legacy CSV without tester, host name, logs or paths."""
    filename = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + session["session_id"] + ".json"
    path = results_dir / filename
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(session, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)
    csv_path = results_dir / "runs.csv"
    # Legacy files have different columns. Do not append incompatible rows to them.
    if csv_path.exists():
        with csv_path.open(encoding="utf-8", newline="") as previous:
            if next(csv.reader(previous), []) != CSV_FIELDS:
                csv_path = results_dir / "runs-v1.csv"
    new = not csv_path.exists()
    with csv_path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        if new:
            writer.writeheader()
        for run in session["runs"]:
            metrics = run["measurements"]
            writer.writerow({"machine_label": session["device"]["alias"], "os": session["device"]["os"],
                             "os_version": session["device"]["os_version"], "cpu_model": session["device"]["cpu_model"],
                             "model_name": session["model"]["name"], "runtime": session["runtime"]["name"],
                             "total_ram_gb": session["device"]["total_ram_gib"], "prompt_id": run["prompt_id"],
                             "run_index": run["repeat_index"], "warmup_round_trip_s": session["warmup_round_trip_s"],
                             "ttft_ms": metrics["ttft_ms"], "tps": metrics["decode_tps"],
                             "output_tokens": run["sources"]["output_tokens"],
                             "cpu_percent_normalized": metrics["cpu_percent_normalized"], "peak_ram_mb": metrics["peak_rss_mib"],
                             "timestamp": run["timestamp"], "status": run["status"]})
    return path
