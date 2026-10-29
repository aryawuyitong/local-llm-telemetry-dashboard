import json
import threading
import unittest
import urllib.error
import urllib.request

from telemetry_agent import helper
from telemetry_agent.config import Settings


def request(port, path, token=None, body=None, host=None):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}",
                                 data=json.dumps(body).encode() if body is not None else None)
    if token:
        req.add_header("X-Lab-Token", token)
    if body is not None:
        req.add_header("Content-Type", "application/json")
    if host:
        req.add_header("Host", host)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        with e:
            return e.code, e.read()


class HelperServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # point at a port where nothing listens, so no test depends on Ollama
        cls.lab = helper.Lab(Settings(base_url="http://127.0.0.1:9/v1"))
        cls.token = "test-token"
        cls.server = helper.create_server(cls.lab, cls.token, port=0)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def test_serves_the_page_without_a_token(self):
        status, body = request(self.port, "/")
        self.assertEqual(status, 200)
        self.assertIn(b"Local AI Lab", body)

    def test_api_needs_the_token(self):
        self.assertEqual(request(self.port, "/api/status")[0], 401)
        self.assertEqual(request(self.port, "/api/status", token="wrong")[0], 401)

    def test_rejects_other_hosts(self):
        # a malicious site that rebinds its domain to 127.0.0.1 still sends its own Host header
        self.assertEqual(request(self.port, "/", host=f"evil.example:{self.port}")[0], 403)

    def test_no_files_outside_the_web_folder(self):
        self.assertEqual(request(self.port, "/../helper.py")[0], 404)
        self.assertEqual(request(self.port, "/%2e%2e/helper.py")[0], 404)

    def test_only_fixed_actions_with_allow_listed_models(self):
        cases = [{"action": "run_shell", "args": {"cmd": "rm -rf ~"}},
                 {"action": "pull_model", "args": {"model": "llama3.1:70b"}},
                 {"action": "start_runtime", "args": {"cmd": "sudo ollama serve"}}]
        for body in cases:
            with self.subTest(body=body):
                self.assertEqual(request(self.port, "/api/jobs", self.token, body)[0], 400)

    def test_status_reports_runtime_down(self):
        status, body = request(self.port, "/api/status", self.token)
        data = json.loads(body)
        self.assertEqual(status, 200)
        self.assertFalse(data["runtime"]["running"])
        self.assertFalse(data["assistant"]["ready"])

    def test_diagnose_works_without_a_model(self):
        status, body = request(self.port, "/api/diagnose", self.token, {"text": "OSError: [Errno 28] No space left on device"})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["matches"][0]["id"], "disk_full")


class Goals(unittest.TestCase):
    rec = {"recommended": {"name": "phi3.5"}, "faster_option": {"name": "qwen2.5:3b"}, "stronger_option": None}

    def test_goal_picks_an_option(self):
        self.assertEqual(helper.pick_for_goal(self.rec, "try")["name"], "qwen2.5:3b")
        self.assertEqual(helper.pick_for_goal(self.rec, "study")["name"], "phi3.5")

    def test_falls_back_when_the_preferred_option_does_not_fit(self):
        self.assertEqual(helper.pick_for_goal(self.rec, "code")["name"], "phi3.5")


if __name__ == "__main__":
    unittest.main()
