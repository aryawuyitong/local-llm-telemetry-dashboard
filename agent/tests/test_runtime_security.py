"""Network/resource boundaries tested without model downloads or real inference."""
import http.client
import json
import tempfile
import threading
import unittest
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from telemetry_agent import helper, system
from telemetry_agent.config import Settings, local_urlopen, validate_local_base_url
from tests.test_helper import request


class RuntimeURLTests(unittest.TestCase):
    def test_only_canonical_loopback_origins(self):
        cases = ["https://127.0.0.1:11434/v1", "http://example.com/v1", "http://127.0.0.1.evil.test/v1",
                 "http://localhost.evil.test/v1", "http://localhost./v1", "http://2130706433/v1",
                 "http://0177.0.0.1/v1", "http://[::ffff:127.0.0.1]/v1", "http://user:pass@127.0.0.1/v1",
                 "http://127.0.0.1/v1?url=http://evil", "http://127.0.0.1/v1#secret", "http://127.0.0.1/api",
                 "http://127.0.0.1/v1/../../api", "http://127.0.0.1:0/v1", "http://127.0.0.1:99999/v1",
                 "http://%31%32%37.0.0.1/v1", "http://127.0.0.1\\@example.com/v1",
                 "http://127.0.0.1/\nv1"]
        for value in cases:
            with self.subTest(value=value), self.assertRaises(ValueError):
                Settings(base_url=value)

    def test_localhost_is_replaced_without_dns_resolution(self):
        with mock.patch("socket.getaddrinfo", side_effect=AssertionError("No DNS should be used")):
            self.assertEqual(validate_local_base_url("http://localhost:11434/v1"), "http://127.0.0.1:11434/v1")
        self.assertEqual(validate_local_base_url("http://[::1]:8080/v1"), "http://[::1]:8080/v1")

    def test_native_request_rejects_noncanonical_or_escaped_path_before_io(self):
        for url in ("http://localhost:11434/api/tags", "http://evil/api/tags",
                    "http://127.0.0.1:11434/api/%2e%2e", "http://127.0.0.1:11434/api/tags?next=evil"):
            with self.subTest(url=url), self.assertRaises(urllib.error.URLError):
                local_urlopen(url, timeout=1)


class RedirectProxyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == "/api/redirect":
                    self.send_response(302)
                    self.send_header("Location", "http://external.invalid/should-not-be-requested")
                    self.end_headers()
                else:
                    self.send_response(200); self.end_headers(); self.wfile.write(b'{"ok":true}')
            def log_message(self, *args):
                pass
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close()

    def test_redirects_are_never_followed(self):
        with self.assertRaisesRegex(urllib.error.URLError, "redirects"):
            local_urlopen(f"http://127.0.0.1:{self.port}/api/redirect", timeout=2)

    def test_environment_proxy_cannot_redirect_local_runtime_traffic(self):
        with mock.patch.dict("os.environ", {"HTTP_PROXY": "http://external.invalid:8080",
                                          "http_proxy": "http://external.invalid:8080", "NO_PROXY": "", "no_proxy": ""}):
            with local_urlopen(f"http://127.0.0.1:{self.port}/api/tags", timeout=2) as response:
                self.assertEqual(json.loads(response.read()), {"ok": True})


class HTTPBodyBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.lab = helper.Lab(Settings(base_url="http://127.0.0.1:9/v1", results_dir=Path(cls.tmp.name)))
        cls.server = helper.create_server(cls.lab, "boundary-token", 0)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.tmp.cleanup()

    def raw_post(self, length, payload=b"{}", content_type="application/json", duplicate_length=False):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        conn.putrequest("POST", "/api/diagnose")
        conn.putheader("X-Lab-Token", "boundary-token")
        conn.putheader("Content-Type", content_type)
        conn.putheader("Content-Length", str(length))
        if duplicate_length:
            conn.putheader("Content-Length", str(length))
        conn.endheaders(payload)
        try:
            response = conn.getresponse()
            status = response.status
            response.read()
            return status
        finally:
            conn.close()

    def test_negative_duplicate_oversize_and_wrong_media_type_are_rejected(self):
        # These headers must be rejected before any body is read. Sending body
        # bytes races the server's close and can reset the connection on Windows.
        for args in [(-1, b""), ("nonnumeric", b""), (helper.MAX_BODY + 1, b""), (2, b"", "text/plain"),
                     (2, b"", "application/json", True)]:
            with self.subTest(args=args):
                self.assertEqual(self.raw_post(*args), 400)

    def test_nonfinite_json_and_nonobject_bodies_are_rejected(self):
        for body in (b'{"text":NaN}', b'{"text":Infinity}', b'["not","object"]'):
            self.assertEqual(self.raw_post(len(body), body), 400)

    def test_duplicate_host_and_origin_are_rejected(self):
        for duplicate in ("Host", "Origin"):
            conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
            conn.putrequest("GET", "/api/status")
            conn.putheader("X-Lab-Token", "boundary-token")
            if duplicate == "Host":
                conn.putheader("Host", f"127.0.0.1:{self.port}")
            else:
                conn.putheader("Origin", f"http://127.0.0.1:{self.port}")
                conn.putheader("Origin", "https://external.invalid")
            conn.endheaders()
            resp = conn.getresponse()
            self.assertEqual(resp.status, 403)
            resp.read(); conn.close()


class FootprintTests(unittest.TestCase):
    def test_portable_runtime_file_expands_to_distribution_with_sibling_libraries(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp).resolve()
            (folder / "ollama").write_bytes(b"runtime")
            (folder / "metal-library.bin").write_bytes(b"required-resource")
            settings = Settings(runtime_install_dir=folder / "ollama", models_dir=folder / "models",
                                results_dir=folder / "results", runtime_models_dir=folder / "store")
            with mock.patch.object(system, "_tree_bytes", return_value=(1024, True)) as measure:
                state = system.installation_footprint(settings)
            self.assertIn(folder, measure.call_args.args[0])
            self.assertNotIn(folder / "ollama", measure.call_args.args[0])
            self.assertTrue(state["runtime_file_expanded_to_distribution"])
            self.assertTrue(state["verified"])

    def test_unknown_runtime_location_is_not_a_budget_pass(self):
        with mock.patch.object(system.shutil, "which", return_value=None), \
             mock.patch.object(Path, "exists", return_value=False), \
             mock.patch.object(system, "_tree_bytes", return_value=(1024, True)):
            result = system.installation_footprint(Settings())
        self.assertFalse(result["verified"])
        self.assertIn("runtime installation location", result["missing"])

    def test_preexisting_base_python_is_not_scanned_as_project_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp).resolve()
            project_env = folder / "project-venv"
            base_python = folder / "preexisting-anaconda"
            project_env.mkdir()
            base_python.mkdir()
            settings = Settings(runtime_install_dir=folder, models_dir=folder / "models",
                                results_dir=folder / "results", runtime_models_dir=folder / "store")
            with mock.patch.object(system.sys, "prefix", str(project_env)), \
                 mock.patch.object(system.sys, "base_prefix", str(base_python)), \
                 mock.patch.object(system, "_tree_bytes", return_value=(1024, True)) as measure:
                result = system.installation_footprint(settings)
            self.assertIn(project_env, measure.call_args.args[0])
            self.assertNotIn(base_python, measure.call_args.args[0])
            self.assertIn(base_python, measure.call_args.args[1])
            self.assertTrue(result["verified"])

    def test_venv_python_symlink_into_preexisting_base_does_not_fail_scan(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp).resolve()
            project_env, base_python = folder / "project-venv", folder / "preexisting-python"
            (project_env / "bin").mkdir(parents=True)
            base_python.mkdir()
            (base_python / "python").write_bytes(b"existing interpreter")
            (project_env / "bin" / "python").symlink_to(base_python / "python")
            self.assertFalse(system._tree_bytes([project_env], [])[1])
            self.assertTrue(system._tree_bytes([project_env], [base_python])[1])

    def test_venv_cfg_python_link_is_known_but_unrelated_external_link_still_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp).resolve()
            project, runtime = folder / "project", folder / "runtime"
            env, base, python_home = project / ".venv", folder / "base", folder / "python-home"
            (env / "bin").mkdir(parents=True)
            base.mkdir(); python_home.mkdir(); runtime.mkdir()
            interpreter = python_home / "python3.13"
            interpreter.write_bytes(b"pre-existing interpreter")
            (env / "bin" / "python3.13").symlink_to(interpreter)
            (env / "pyvenv.cfg").write_text(f"home = {python_home}\nexecutable = {interpreter}\n", encoding="utf-8")
            settings = Settings(runtime_install_dir=runtime, models_dir=project / "models",
                                results_dir=project / "results", runtime_models_dir=folder / "models")
            with mock.patch("telemetry_agent.config.ROOT", project), \
                 mock.patch.object(system.sys, "prefix", str(env)), \
                 mock.patch.object(system.sys, "base_prefix", str(base)):
                self.assertTrue(system.installation_footprint(settings)["verified"])
                unrelated = folder / "unrelated.bin"
                unrelated.write_bytes(b"unknown external file")
                (env / "bin" / "other-tool").symlink_to(unrelated)
                self.assertIn("complete filesystem scan", system.installation_footprint(settings)["missing"])


if __name__ == "__main__":
    unittest.main()
