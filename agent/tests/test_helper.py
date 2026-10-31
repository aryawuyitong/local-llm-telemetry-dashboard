import copy
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

from telemetry_agent import helper, protocol
from telemetry_agent.config import ROOT, Settings


def request(port, path, token=None, body=None, host=None, origin=None, headers=None):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}",
                                 data=json.dumps(body).encode() if body is not None else None)
    if token:
        req.add_header("X-Lab-Token", token)
    if body is not None:
        req.add_header("Content-Type", "application/json")
    if host:
        req.add_header("Host", host)
    if origin is not None:
        req.add_header("Origin", origin)
    for key, value in (headers or {}).items():
        req.add_header(key, value)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as exc:
        with exc:
            return exc.code, exc.read()


class HelperServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.folder = Path(cls.tmp.name)
        cls.lab = helper.Lab(Settings(base_url="http://127.0.0.1:9/v1",
                                      models_dir=cls.folder / "models", results_dir=cls.folder / "results"))
        cls.token = "test-token"
        cls.server = helper.create_server(cls.lab, cls.token, port=0)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.tmp.cleanup()

    def test_page_static_bootstrap_and_security_headers(self):
        status, body = request(self.port, "/")
        self.assertEqual(status, 200)
        self.assertIn(b"manual", body.lower())
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/") as resp:
            self.assertIn("frame-ancestors 'none'", resp.headers["Content-Security-Policy"])
            self.assertEqual(resp.headers["Referrer-Policy"], "no-referrer")
            self.assertEqual(resp.headers["Cache-Control"], "no-store")

    def test_token_host_and_origin_are_all_required_when_supplied(self):
        for token in (None, "wrong"):
            self.assertEqual(request(self.port, "/api/status", token)[0], 401)
        self.assertEqual(request(self.port, "/", host=f"evil.example:{self.port}")[0], 403)
        self.assertEqual(request(self.port, "/api/status", self.token, origin="https://evil.example")[0], 403)
        self.assertEqual(request(self.port, "/api/status", self.token, origin=f"http://127.0.0.1:{self.port}")[0], 200)
        self.assertEqual(request(self.port, "/api/status", self.token, headers={"Sec-Fetch-Site": "cross-site"})[0], 403)

    def test_cross_site_top_level_navigation_only_does_not_relax_api_boundary(self):
        headers = {"Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "document"}
        self.assertEqual(request(self.port, "/", headers=headers)[0], 200)
        self.assertEqual(request(self.port, "/index.html", headers=headers)[0], 200)
        self.assertEqual(request(self.port, "/api/status", self.token, headers=headers)[0], 403)
        self.assertEqual(request(self.port, "/app.js", headers=headers)[0], 403)
        self.assertEqual(request(self.port, "/", headers={**headers, "Sec-Fetch-Mode": "cors"})[0], 403)
        self.assertEqual(request(self.port, "/", origin="https://external.invalid", headers=headers)[0], 403)

    def test_no_path_traversal_encoded_queries_or_token_query(self):
        for path in ("/../helper.py", "/%2e%2e/helper.py", "//api/status", "/api/status?t=test-token"):
            with self.subTest(path=path):
                self.assertIn(request(self.port, path, self.token)[0], (400, 404))

    def test_install_and_download_are_not_background_actions(self):
        for action in ("start_runtime", "pull_model", "run_shell"):
            body = {"action": action, "args": {"model": "qwen2.5:0.5b"}}
            self.assertEqual(request(self.port, "/api/jobs", self.token, body)[0], 400)

    def test_action_argument_types_unknown_model_and_extra_fields(self):
        cases = [{"action": "first_prompt", "args": {"model": "unknown"}},
                 {"action": "check_hardware", "args": []},
                 {"action": "check_hardware", "args": {"cmd": "echo hi"}},
                 {"action": "benchmark", "args": {"model": "qwen2.5:0.5b", "repeats": True}},
                 {"action": "benchmark", "args": {"model": "qwen2.5:0.5b", "guess_ram_gb": "4"}},
                 {"action": "check_hardware", "extra": 1}]
        for body in cases:
            with self.subTest(body=body):
                self.assertEqual(request(self.port, "/api/jobs", self.token, body)[0], 400)

    def test_status_and_rule_help_need_no_model(self):
        status, body = request(self.port, "/api/status", self.token)
        self.assertEqual(status, 200)
        self.assertFalse(json.loads(body)["assistant"]["ready"])
        status, body = request(self.port, "/api/diagnose", self.token,
                               {"text": "OSError: [Errno 28] No space left on device"})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["matches"][0]["id"], "disk_full")
        status, body = request(self.port, "/api/chat", self.token, {"message": "What is next?"})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["mode"], "static_bootstrap")

    def test_live_guardrails_cannot_be_disabled_or_coerced(self):
        for value in (False, "false", 0, None):
            self.assertEqual(request(self.port, "/api/chat", self.token,
                                      {"message": "test", "guardrails": value})[0], 400)

    def test_plan_is_manual_and_never_assumes_first_model(self):
        status, body = request(self.port, "/api/plan", self.token, {"model": "qwen2.5:0.5b"})
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(data["installation_mode"], "manual")
        for step in data["steps"]:
            if step["id"] in {"start_runtime", "pull_model", "install_runtime"}:
                self.assertEqual(step["kind"], "manual")
                self.assertIsNone(step["action"])

    def test_json_download_rebuilds_summary_and_removes_private_labels(self):
        fixture = ROOT.parent / "portal/examples/synthetic-session.json"
        data = json.loads(fixture.read_text(encoding="utf-8"))
        data["session_id"], data["device"]["alias"] = "AliceExample", "AliceExample"
        data["summary"]["note"] = "private /Users/AliceExample/private.txt password=sample_secret_value"
        folder = self.lab.settings.results_dir
        folder.mkdir(exist_ok=True)
        path = folder / "test-session.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        try:
            status, body = request(self.port, "/api/results.json", self.token)
            self.assertEqual(status, 200)
            out = json.loads(body)
            protocol.validate_session(out)
            self.assertNotIn(b"AliceExample", body)
            self.assertNotIn(b"private.txt", body)
            self.assertNotIn(b"sample_secret_value", body)
            self.assertEqual(out["data_kind"], "synthetic")
            self.assertIn("SIMULATED", out["summary"]["note"])
            self.assertEqual(out["summary"]["runs"], len(out["runs"]))
        finally:
            path.unlink()

    def test_jobs_are_atomic_deduplicated_and_inference_is_serialized(self):
        entered, finish = threading.Event(), threading.Event()
        def slow(job):
            entered.set(); finish.wait(3)
            return {"ok": True}
        with mock.patch.object(self.lab, "_do_check_hardware", side_effect=slow):
            first = self.lab.start_job("check_hardware", {})
            try:
                self.assertTrue(entered.wait(2))
                self.assertEqual(self.lab.start_job("check_hardware", {})["id"], first["id"])
                with self.assertRaises(helper.Busy):
                    self.lab.start_job("check_install", {"up_to_step": 2})
                with self.assertRaises(helper.Busy):
                    self.lab.try_model("qwen2.5:0.5b", "test")
            finally:
                finish.set()
                for _ in range(100):
                    if self.lab.job(first["id"])["status"] != "running":
                        break
                    threading.Event().wait(0.01)
        self.assertEqual(self.lab.job(first["id"])["status"], "done")


class LabLogic(unittest.TestCase):
    def setUp(self):
        self.lab = helper.Lab(Settings(base_url="http://127.0.0.1:9/v1"))

    def test_secret_detection_reaches_agent_but_secret_never_reaches_model(self):
        class CaptureModel:
            def chat(self, messages, **kwargs):
                self.messages = [dict(item) for item in messages]
                return {"content": "Revoke or change the secret you pasted. Do not share secrets."}
        model, capture = "qwen2.5:0.5b", CaptureModel()
        local = helper.LabAgent(Settings(agent_model=model, router=False), llm=capture)
        self.lab._agents[model] = local
        with mock.patch.object(self.lab, "runtime_state", return_value={"lab_models": [model]}), \
             mock.patch.object(self.lab.tools, "ensure_model_ready", return_value={}):
            answer = self.lab.chat("My password is FakeSecretZebra2026!")
        self.assertNotIn("FakeSecretZebra2026", json.dumps(capture.messages))
        self.assertIn("revoke/change it now", capture.messages[-1]["content"])
        self.assertIn("Revoke or change", answer["text"])

    def test_all_failed_benchmark_is_not_a_success_job(self):
        job = {"action": "benchmark", "args": {"model": "qwen2.5:0.5b"}}
        self.lab._operation_lock.acquire()
        with mock.patch.object(self.lab, "_do_benchmark", return_value={"runs": 9, "failed_runs": 9, "partial_runs": 0}):
            self.lab._run_job(job)
        self.assertEqual(job["status"], "failed")
        self.assertEqual(job["result"]["failed_runs"], 9)
        self.assertIn("saved", job["error"])

    def test_partial_benchmark_is_explicitly_limited(self):
        job = {"action": "benchmark", "args": {"model": "qwen2.5:0.5b"}}
        self.lab._operation_lock.acquire()
        with mock.patch.object(self.lab, "_do_benchmark", return_value={"runs": 9, "failed_runs": 0, "partial_runs": 9}):
            self.lab._run_job(job)
        self.assertEqual(job["status"], "partial")
        self.assertIn("not complete acceptance", job["warning"])

    def test_static_bootstrap_explains_metrics_without_an_llm(self):
        answer = self.lab._bootstrap_text("What does tokens per second mean?")
        self.assertIn("runtime-reported", answer)
        self.assertIn("proxy", answer)

    def test_try_model_uses_native_duration_without_chunk_counting(self):
        frames = [(1.0, "A multi-token text chunk", None), (2.0, "", {
            "source": "ollama_native", "eval_count": 12, "completion_tokens": 12, "eval_duration": 2000000000})]
        with mock.patch.object(self.lab.tools, "ensure_model_ready", return_value={}), \
             mock.patch.object(helper.ChatClient, "benchmark_stream", return_value=iter(frames)), \
             mock.patch.object(helper.time, "perf_counter", return_value=0.5):
            result = self.lab.try_model("qwen2.5:0.5b", "Say something")
        self.assertEqual(result["tps"], 6)
        self.assertEqual(result["tokens"], 12)
        self.assertEqual(result["ttft_s"], 0.5)

    def test_huge_runtime_counters_are_structured_rejections_not_overflow(self):
        for usage in ({"source": "ollama_native", "eval_count": 12, "eval_duration": 10**1000},
                      {"source": "ollama_native", "eval_count": 10**1000, "eval_duration": 1000000},
                      {"completion_tokens": 10**1000}):
            frames = [(1.0, "Some output", usage)]
            with self.subTest(fields=list(usage)), \
                 mock.patch.object(self.lab.tools, "ensure_model_ready", return_value={}), \
                 mock.patch.object(helper.ChatClient, "benchmark_stream", return_value=iter(frames)), \
                 self.assertRaisesRegex(ValueError, "local runtime returned an invalid"):
                self.lab.try_model("qwen2.5:0.5b", "Say something")


if __name__ == "__main__":
    unittest.main()
