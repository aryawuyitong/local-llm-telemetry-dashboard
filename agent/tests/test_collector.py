import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from telemetry_agent import collector
from telemetry_agent.config import Settings
from telemetry_agent.llm import ChatClient, LLMError
from telemetry_agent.protocol import load_session


class FakeRuntime(BaseHTTPRequestHandler):
    mode = "ok"
    requests = []

    def log_message(self, *args):
        pass

    def _send(self, payload, code=200):
        data = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/api/version":
            return self._send({"version": "/Users/private password secret" if type(self).mode == "metadata_private" else "test-1"})
        if self.path in ("/api/tags", "/api/ps"):
            return self._send({"models": [{"name": "qwen2.5:1.5b", "digest": "a" * 64,
                        "details": {"quantization_level": "Q4_K_M"}, "size": 100,
                        "size_vram": 0, "context_length": 2048}]})
        if self.path == "/v1/models":
            return self._send({"data": [{"id": "qwen2.5:1.5b"}]})
        return self._send({}, 404)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        type(self).requests.append((self.path, body))
        if type(self).mode == "failure" or (type(self).mode == "one_failure" and len(type(self).requests) == 3):
            return self._send({"error": "private /Users/example password: secret"}, 500)
        if self.path == "/api/chat":
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.end_headers()
            self.wfile.write(json.dumps({"message": {"content": "A whole sentence in one chunk."}, "done": False}).encode() + b"\n")
            self.wfile.flush()
            if type(self).mode == "truncated":
                return
            final = {"done": True, "message": {"content": ""}}
            if type(self).mode != "missing":
                final.update(eval_count=1000 if type(self).mode == "bad_count" else 120, eval_duration=2_000_000_000)
            self.wfile.write(json.dumps(final).encode() + b"\n")
            return
        if self.path == "/v1/chat/completions":
            if not body.get("stream"):
                return self._send({"choices": [{"message": {"role": "assistant", "content": "Ready"}}]})
            self.send_response(200)
            self.end_headers()
            chunks = [{"choices": [{"delta": {"content": "many tokens in one chunk"}}]},
                      {"choices": [], "usage": {"completion_tokens": 5}}]
            for chunk in chunks:
                self.wfile.write(b"data: " + json.dumps(chunk).encode() + b"\n\n")
            self.wfile.write(b"data: [DONE]\n\n")
            return
        self._send({}, 404)


@contextmanager
def runtime():
    FakeRuntime.mode = "ok"
    FakeRuntime.requests = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeRuntime)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/v1"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


class NoProcesses:
    interval = .1
    cpu_samples = []
    peak_rss = None
    flags = set()
    process_count = 0

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class NativeMeasurement(unittest.TestCase):
    def test_native_tps_uses_runtime_count_and_duration_not_chunks(self):
        with runtime() as url, mock.patch.object(collector, "ResourceSampler", NoProcesses):
            client = ChatClient(url, "qwen2.5:1.5b")
            result = collector.measure_once(client, "Fixed prompt", "ollama")
            self.assertEqual(result["tps"], 60)
            self.assertEqual(result["output_tokens"], 120)
            self.assertEqual(result["sources"]["decode_duration_s"], 2)
            self.assertIsNotNone(result["ttft_ms"])
            self.assertIsNone(result["peak_ram_mb"])
            self.assertEqual(result["status"], "partial")
            self.assertIn("process_attribution_unavailable", result["quality_flags"])
            opts = FakeRuntime.requests[-1][1]["options"]
            self.assertEqual(opts, {"temperature": 0, "num_predict": 128, "num_ctx": 2048})

    def test_missing_native_usage_keeps_tps_null(self):
        with runtime() as url, mock.patch.object(collector, "ResourceSampler", NoProcesses):
            FakeRuntime.mode = "missing"
            result = collector.measure_once(ChatClient(url, "qwen2.5:1.5b"), "Prompt", "ollama")
            self.assertIsNone(result["tps"])
            self.assertIsNone(result["output_tokens"])
            self.assertIn("decode_timing_unavailable", result["quality_flags"])

    def test_invalid_runtime_token_counts_are_not_exported(self):
        with runtime() as url, mock.patch.object(collector, "ResourceSampler", NoProcesses):
            FakeRuntime.mode = "bad_count"
            result = collector.measure_once(ChatClient(url, "qwen2.5:1.5b"), "Prompt", "ollama")
            self.assertIsNone(result["tps"])
            self.assertIsNone(result["output_tokens"])
            self.assertIn("token_count_out_of_bounds", result["quality_flags"])

    def test_truncated_native_stream_is_an_error_even_after_some_text(self):
        with runtime() as url, mock.patch.object(collector, "ResourceSampler", NoProcesses):
            FakeRuntime.mode = "truncated"
            result = collector.measure_once(ChatClient(url, "qwen2.5:1.5b"), "Prompt", "ollama")
            self.assertEqual(result["status"], "error")
            self.assertIsNotNone(result["ttft_ms"])
            self.assertNotIn("/Users", result["error"])

    def test_legacy_stream_interface_stays_three_items_and_does_not_invent_decode_time(self):
        with runtime() as url, mock.patch.object(collector, "ResourceSampler", NoProcesses):
            client = ChatClient(url, "qwen2.5:1.5b")
            chunks = list(client.stream([{"role": "user", "content": "hello"}]))
            self.assertTrue(all(len(chunk) == 3 for chunk in chunks))
            self.assertEqual(chunks[-1][2]["completion_tokens"], 5)
            result = collector.measure_once(client, "Prompt", "llama.cpp")
            self.assertIsNone(result["tps"])
            self.assertEqual(result["output_tokens"], 5)

    def test_session_defaults_nine_runs_and_anonymous_versioned_export(self):
        with tempfile.TemporaryDirectory() as folder, runtime() as url, mock.patch.object(collector, "ResourceSampler", NoProcesses):
            settings = Settings(base_url=url, results_dir=Path(folder))
            summary = collector.run_benchmark("qwen2.5:1.5b", settings, tester="Private Name", guess_tps=40, guess_ram_gb=2)
            doc = load_session(Path(summary["saved_to"]))
            self.assertEqual(len(doc["runs"]), 9)
            self.assertEqual(doc["summary"]["median_tps"], 60)
            self.assertEqual(doc["model"]["digest"], "a" * 64)
            self.assertEqual(doc["runtime"]["version"], "test-1")
            self.assertEqual(doc["predictions"], {"tps": 40, "ram_gib": 2})
            self.assertEqual(doc["config"]["repeats"], 3)
            raw = json.dumps(doc)
            for private in ("Private Name", url, "saved_to", "load_time_s", "A whole sentence", "Fixed prompt"):
                self.assertNotIn(private, raw)
            self.assertEqual(len(FakeRuntime.requests), 10)

    def test_failed_warmup_is_retained_without_repeating_nine_failed_requests(self):
        with tempfile.TemporaryDirectory() as folder, runtime() as url:
            FakeRuntime.mode = "failure"
            summary = collector.run_benchmark("qwen2.5:1.5b", Settings(base_url=url, results_dir=Path(folder)))
            doc = load_session(Path(summary["saved_to"]))
            self.assertEqual(summary["failed_runs"], 9)
            self.assertEqual(summary["valid_runs"], 0)
            self.assertIsNone(summary["median_tps"])
            self.assertTrue(all(r["status"] == "error" for r in doc["runs"]))
            self.assertNotIn("secret", json.dumps(doc))
            self.assertEqual(len(FakeRuntime.requests), 1)

    def test_one_failed_run_stays_in_denominator_and_later_runs_continue(self):
        with tempfile.TemporaryDirectory() as folder, runtime() as url, mock.patch.object(collector, "ResourceSampler", NoProcesses):
            FakeRuntime.mode = "one_failure"
            summary = collector.run_benchmark("qwen2.5:1.5b", Settings(base_url=url, results_dir=Path(folder)))
            doc = load_session(Path(summary["saved_to"]))
            self.assertEqual(summary["failed_runs"], 1)
            self.assertEqual(summary["runs"], 9)
            self.assertEqual(summary["decode_tps_valid_count"], 8)
            self.assertEqual(summary["per_prompt"]["short"]["failed_runs"], 1)
            self.assertEqual(len(FakeRuntime.requests), 10)
            self.assertNotIn("private", json.dumps(doc))

    def test_metadata_does_not_copy_arbitrary_private_runtime_text(self):
        with runtime() as url:
            FakeRuntime.mode = "metadata_private"
            metadata = ChatClient(url, "qwen2.5:1.5b").metadata()
            self.assertIsNone(metadata["runtime_version"])
            self.assertNotIn("private", json.dumps(metadata))

    def test_bad_inputs_fail_before_request_or_output(self):
        with tempfile.TemporaryDirectory() as folder:
            settings = Settings(results_dir=Path(folder))
            cases = [{"repeats": True}, {"repeats": 4}, {"prompt_ids": ["short", "short"]},
                     {"guess_tps": float("nan")}, {"guess_tps": 10**1000}, {"machine_label": "/Users/private"}]
            for kwargs in cases:
                with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                    collector.run_benchmark("qwen2.5:1.5b", settings, **kwargs)
            with self.assertRaises(ValueError):
                collector.run_benchmark("unapproved:70b", settings)
            self.assertEqual(list(Path(folder).iterdir()), [])


class ProcessesAndLock(unittest.TestCase):
    def test_listener_lookup_ignores_unrelated_ports_and_interfaces(self):
        entries = [SimpleNamespace(status="LISTEN", laddr=SimpleNamespace(port=11434, ip="127.0.0.1"), pid=10),
                   SimpleNamespace(status="LISTEN", laddr=SimpleNamespace(port=11434, ip="192.0.2.5"), pid=20),
                   SimpleNamespace(status="LISTEN", laddr=SimpleNamespace(port=9999, ip="127.0.0.1"), pid=30)]
        with mock.patch.object(collector.psutil, "net_connections", return_value=entries), \
                mock.patch.object(collector.psutil, "Process", side_effect=lambda pid: pid):
            self.assertEqual(collector.runtime_processes("ollama", "http://127.0.0.1:11434/v1"), [10])

    def test_refreshes_children_including_one_that_appears_mid_request(self):
        def process(pid, cpu, rss):
            return SimpleNamespace(pid=pid, create_time=lambda: pid, cpu_times=lambda: SimpleNamespace(user=cpu[0], system=0),
                                   memory_info=lambda: SimpleNamespace(rss=rss), children=lambda recursive=True: [])
        clock, root_cpu, child_cpu = [0.0], [0.0], [0.0]
        root = process(1, root_cpu, 1024)
        child = process(2, child_cpu, 2048)
        children = []
        root.children = lambda recursive=True: children
        sampler = collector.ResourceSampler(process_provider=lambda: [root])
        sampler.cores = 2
        with mock.patch.object(collector.time, "perf_counter", side_effect=lambda: clock[0]):
            sampler._sample()
            children.append(child)
            clock[0], root_cpu[0] = 1.0, .2
            sampler._sample()
            clock[0], root_cpu[0], child_cpu[0] = 2.0, .4, .6
            sampler._sample()
        self.assertEqual(sampler.process_count, 2)
        self.assertEqual(sampler.peak_rss, 3072)
        self.assertAlmostEqual(sampler.cpu_samples[-1], 40)

    def test_os_level_child_discovery_denial_never_becomes_false_complete_metrics(self):
        root = SimpleNamespace(pid=1, create_time=lambda: 1,
                    cpu_times=lambda: SimpleNamespace(user=.1, system=.1),
                    memory_info=lambda: SimpleNamespace(rss=1024),
                    children=mock.Mock(side_effect=PermissionError("OS process enumeration denied")))
        sampler = collector.ResourceSampler(process_provider=lambda: [root])
        sampler._sample()
        self.assertFalse(sampler.attribution_complete)
        self.assertIn("child_process_discovery_unavailable", sampler.flags)
        with runtime() as url, mock.patch.object(collector, "runtime_processes", return_value=[root]):
            result = collector.measure_once(ChatClient(url, "qwen2.5:1.5b"), "Prompt", "ollama")
            self.assertIsNone(result["cpu_percent_normalized"])
            self.assertIsNone(result["peak_ram_mb"])
            self.assertEqual(result["sources"]["process_attribution"], "unavailable")

    def test_thread_and_os_lock_reject_overlap_and_release_after_error(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            with self.assertRaisesRegex(RuntimeError, "boom"):
                with collector._exclusive_benchmark(directory):
                    with self.assertRaisesRegex(RuntimeError, "already"):
                        with collector._exclusive_benchmark(directory):
                            pass
                    script = "from pathlib import Path; from telemetry_agent.collector import _exclusive_benchmark; " \
                             "\nwith _exclusive_benchmark(Path(__import__('sys').argv[1])): pass"
                    outcome = subprocess.run([sys.executable, "-c", script, folder], capture_output=True, text=True)
                    self.assertNotEqual(outcome.returncode, 0)
                    self.assertIn("already running", outcome.stderr)
                    raise RuntimeError("boom")
            with collector._exclusive_benchmark(directory):
                pass


if __name__ == "__main__":
    unittest.main()
