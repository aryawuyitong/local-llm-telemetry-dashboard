"""Optional Auto setup: the confirmation gate, scope and the local pull client."""
import json
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from telemetry_agent import helper
from telemetry_agent.config import Settings
from telemetry_agent.llm import ChatClient, LLMError
from tests.test_helper import request

RUNNING = {"name": "Ollama", "installed": True, "running": True, "models": [], "lab_models": []}
HW = {"free_disk_gb": 50.0, "available_ram_gb": 12.0, "running_as_admin": False}


def make_lab(folder):
    return helper.Lab(Settings(base_url="http://127.0.0.1:9/v1",
                               models_dir=folder / "models", results_dir=folder / "results"))


class AutoGate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.lab = make_lab(Path(self.tmp.name))
        model = "qwen2.5:1.5b"
        pick = {"name": model, "params_billion": 1.5, "needs_free_ram_gb": 3.0}
        self.patches = [
            mock.patch.object(self.lab, "runtime_state", return_value=dict(RUNNING)),
            mock.patch.object(self.lab.tools, "check_hardware", return_value=dict(HW)),
            mock.patch.object(self.lab, "recommend", return_value={"pick": pick, "goal_why": "x"}),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_plan_is_read_only_and_issues_code(self):
        with mock.patch.object(ChatClient, "pull") as pull:
            plan = self.lab.auto_plan("study")
            pull.assert_not_called()
        self.assertEqual(plan["model"]["name"], "qwen2.5:1.5b")
        self.assertTrue(plan["confirm_code"])
        self.assertFalse(self.lab.jobs)

    def test_start_requires_matching_unexpired_single_use_code(self):
        with mock.patch.object(self.lab, "_launch", return_value={"id": "x"}) as launch:
            for bad in ("", None, 123, "wrong-code-123"):
                self.lab.auto_plan("study")
                with self.subTest(code=bad), self.assertRaises(helper.BadRequest):
                    self.lab.auto_start(bad)
            code = self.lab.auto_plan("study")["confirm_code"]
            self.lab.auto_start(code)
            launch.assert_called_once_with("auto", {"model": "qwen2.5:1.5b"})
            with self.assertRaises(helper.BadRequest):
                self.lab.auto_start(code)  # reuse
            code = self.lab.auto_plan("study")["confirm_code"]
            with mock.patch.object(helper.time, "monotonic", return_value=time.monotonic() + 10_000), \
                    self.assertRaises(helper.BadRequest):
                self.lab.auto_start(code)  # expired
            self.assertEqual(launch.call_count, 1)

    def test_new_plan_invalidates_old_code(self):
        old = self.lab.auto_plan("study")["confirm_code"]
        self.lab.auto_plan("study")
        with self.assertRaises(helper.BadRequest):
            self.lab.auto_start(old)

    def test_stops_without_code_when_runtime_missing_or_admin(self):
        self.lab.runtime_state.return_value = {**RUNNING, "installed": False, "running": False}
        plan = self.lab.auto_plan("study")
        self.assertIsNone(plan["confirm_code"])
        self.assertIn("never installs", plan["stop"])
        self.lab.runtime_state.return_value = dict(RUNNING)
        self.lab.tools.check_hardware.return_value = {**HW, "running_as_admin": True}
        self.assertIsNone(self.lab.auto_plan("study")["confirm_code"])

    def test_stops_when_download_would_break_disk_reserve(self):
        self.lab.tools.check_hardware.return_value = {**HW, "free_disk_gb": 2.5}
        plan = self.lab.auto_plan("study")
        self.assertIsNone(plan["confirm_code"])
        self.assertIn("reserve", plan["stop"])

    def test_auto_job_pulls_verifies_and_prompts(self):
        with mock.patch.object(ChatClient, "pull") as pull, \
                mock.patch.object(self.lab.tools, "ensure_model_ready") as ready, \
                mock.patch.object(self.lab, "_do_first_prompt", return_value={"reply": "Hi there friend", "seconds": 0.4}):
            job = self.lab.auto_start(self.lab.auto_plan("study")["confirm_code"])
            for _ in range(100):
                if self.lab.job(job["id"])["status"] != "running":
                    break
                time.sleep(0.02)
            done = self.lab.job(job["id"])
        self.assertEqual(done["status"], "done", done.get("error"))
        pull.assert_called_once()
        self.assertEqual(pull.call_args[0][0], "qwen2.5:1.5b")
        ready.assert_called_with("qwen2.5:1.5b")
        self.assertTrue(done["result"]["pulled"])


class AutoHttp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.lab = make_lab(Path(cls.tmp.name))
        cls.server = helper.create_server(cls.lab, "t0ken", port=0)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.tmp.cleanup()

    def test_endpoints_need_token_and_confirmation(self):
        self.assertEqual(request(self.port, "/api/auto/plan", None, {})[0], 401)
        self.assertEqual(request(self.port, "/api/auto/start", "t0ken", {})[0], 400)
        self.assertEqual(request(self.port, "/api/auto/start", "t0ken", {"confirm_code": "guess-guess-guess"})[0], 400)
        self.assertEqual(request(self.port, "/api/auto/start", "t0ken", {"confirm_code": "x" * 20, "model": "mistral:7b"})[0], 400)

    def test_plan_stops_when_runtime_is_down(self):
        status, body = request(self.port, "/api/auto/plan", "t0ken", {"goal": "study"})
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertIsNone(data["confirm_code"])
        self.assertTrue(data["stop"])
        self.assertEqual(request(self.port, "/api/auto/plan", "t0ken", {"goal": "rm -rf"})[0], 400)


class FakeOllama(BaseHTTPRequestHandler):
    frames = []
    seen = []

    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeOllama.seen.append((self.path, body))
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.end_headers()
        for frame in FakeOllama.frames:
            self.wfile.write((json.dumps(frame) + "\n").encode())


class PullClient(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeOllama)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.client = ChatClient(f"http://127.0.0.1:{cls.server.server_address[1]}/v1", "qwen2.5:1.5b")

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_streams_progress_until_success(self):
        FakeOllama.frames = [{"status": "pulling manifest"}, {"status": "pulling abc", "total": 100, "completed": 40},
                             {"status": "verifying sha256 digest"}, {"status": "success"}]
        seen = []
        self.client.pull("qwen2.5:1.5b", lambda *a: seen.append(a))
        self.assertEqual(FakeOllama.seen[-1], ("/api/pull", {"model": "qwen2.5:1.5b", "stream": True}))
        self.assertIn(("pulling abc", 40, 100), seen)
        self.assertEqual(seen[-1][0], "success")

    def test_error_or_missing_success_raises(self):
        for frames in ([{"status": "pulling"}, {"error": "file does not exist"}], [{"status": "pulling"}]):
            FakeOllama.frames = frames
            with self.subTest(frames=frames), self.assertRaises(LLMError):
                self.client.pull("qwen2.5:1.5b")

    def test_rejects_paths_urls_and_flags(self):
        for bad in ("../x", "https://evil/x", "--insecure", "a b", "", "Qwen:1"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.client.pull(bad)


if __name__ == "__main__":
    unittest.main()
