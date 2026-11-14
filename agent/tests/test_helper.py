import copy
import dataclasses
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
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
        self.assertIn(b"nothing changes until you approve it", body.lower())  # the approve-to-run promise is on the page
        self.assertIn(b'<script src="lab.js">', body)
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/") as resp:
            self.assertIn("frame-ancestors 'none'", resp.headers["Content-Security-Policy"])
            self.assertEqual(resp.headers["Referrer-Policy"], "no-referrer")
            self.assertEqual(resp.headers["Cache-Control"], "no-store")

    def test_a_burst_of_connections_like_a_page_load_all_get_answers(self):
        self.assertGreaterEqual(self.server.request_queue_size, 64)
        with ThreadPoolExecutor(max_workers=60) as pool:
            codes = list(pool.map(lambda _: request(self.port, "/lab.css")[0], range(240)))
        self.assertEqual(set(codes), {200})

    def test_the_website_is_served_but_not_its_tests_or_notes(self):
        for path in ("/", "/lab.js", "/guide.js", "/examples/synthetic-session.json", "/vendor/hairline.js", "/figures.js", "/motion.js"):
            self.assertEqual(request(self.port, path)[0], 200, path)
        for path in ("/README.md", "/tests/guide.test.js", "/vendor/string-tune.LICENSE", "/vendor/hairline.LICENSE", "/../agent/requirements.txt"):
            self.assertEqual(request(self.port, path)[0], 404, path)

    def test_fonts_are_served_and_nothing_else_in_that_folder(self):
        self.assertEqual(request(self.port, "/fonts/hanken-grotesk.woff2")[0], 200)
        self.assertEqual(request(self.port, "/fonts/README.txt")[0], 404)
        self.assertEqual(request(self.port, "/fonts/../helper.py")[0], 404)

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

    def test_only_fixed_steps_can_run(self):
        for action in ("install_runtime", "run_shell"):
            body = {"action": action, "args": {"model": "qwen2.5:0.5b"}}
            self.assertEqual(request(self.port, "/api/jobs", self.token, body)[0], 400)
        for action in ("pull_model", "remove_model"):
            body = {"action": action, "args": {"model": "not-on-the-list"}}
            self.assertEqual(request(self.port, "/api/jobs", self.token, body)[0], 400)
        self.assertEqual(request(self.port, "/api/jobs", self.token, {"action": "start_runtime", "args": {"cmd": "x"}})[0], 400)

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
        self.assertEqual(json.loads(body)["mode"], "checked")
        status, body = request(self.port, "/api/chat", self.token, {"message": "Tell me a story about a boat"})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["mode"], "static_bootstrap")

    def test_live_guardrails_cannot_be_disabled_or_coerced(self):
        for value in (False, "false", 0, None):
            self.assertEqual(request(self.port, "/api/chat", self.token,
                                      {"message": "test", "guardrails": value})[0], 400)

    def test_plan_is_transparent_and_never_runs_an_installer(self):
        status, body = request(self.port, "/api/plan", self.token, {"model": "qwen2.5:0.5b"})
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(data["installation_mode"], "guided")
        steps = {s["id"]: s for s in data["steps"]}
        self.assertEqual(steps["install_runtime"]["kind"], "manual")
        self.assertIsNone(steps["install_runtime"]["action"])
        self.assertEqual(steps["pull_model"]["action"], "pull_model")
        self.assertIn("ollama pull qwen2.5:0.5b", steps["pull_model"]["command"])
        for step in data["steps"]:
            self.assertTrue(step["what"] and step["why"] and step["does"] and step["brief"], step["id"])
        for step_id in ("start_runtime", "pull_model"):
            self.assertTrue(steps[step_id]["undo"])

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
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.lab = helper.Lab(Settings(base_url="http://127.0.0.1:9/v1", results_dir=Path(tmp.name)))

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

    def _temp_lab(self, available=2.0, total=16.0, disk=30.0):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        lab = helper.Lab(Settings(base_url="http://127.0.0.1:9/v1", results_dir=Path(tmp.name)))
        hw = {"os": "macOS", "cpu_model": "Test", "total_ram_gb": total, "available_ram_gb": available,
              "free_disk_gb": disk, "running_as_admin": False}
        patcher = mock.patch.object(lab.tools, "check_hardware", return_value=hw)
        patcher.start()
        self.addCleanup(patcher.stop)
        return lab

    def test_compatibility_gives_a_plain_verdict_before_any_download(self):
        lab = self._temp_lab()
        verdicts = {m["name"]: m["verdict"] for m in lab.compatibility()["models"]}
        self.assertEqual(verdicts["qwen2.5:0.5b"], "yes")
        self.assertEqual(verdicts["qwen2.5:3b"], "close_apps")
        self.assertEqual(self._temp_lab(total=8.0)._planning_ram({"available_ram_gb": 2.0, "total_ram_gb": 8.0}), 4.0)
        self.assertEqual({m["verdict"] for m in self._temp_lab(available=8, disk=2.2).compatibility()["models"]}, {"no"})

    def test_goal_picks_prefer_ready_models_with_no_license_step(self):
        lab = self._temp_lab(available=3.2)
        self.assertEqual(lab._goal_pick("try")[0]["name"], "qwen2.5:1.5b")
        self.assertEqual(lab._goal_pick("study")[0]["name"], "qwen2.5:1.5b")
        self.assertGreater(lab._goal_pick("code")[0]["params_billion"], 1.5)
        for goal in ("try", "study", "code"):
            self.assertTrue(all(not o["requires_license_acceptance"] for o in lab._goal_pick(goal)[1]))
        self.assertEqual(self._temp_lab(available=0.5, total=1).recommend("try")["options"], [])

    def test_activity_records_checks_without_changing_the_change_list(self):
        lab = self._temp_lab()
        lab._operation_lock.acquire()
        lab._run_job({"action": "check_hardware", "args": {}})
        lab._operation_lock.acquire()
        with mock.patch.object(lab, "_do_benchmark", return_value={"runs": 9, "failed_runs": 0, "partial_runs": 0, "median_tps": 22.4, "peak_ram_mb": 1218}):
            lab._run_job({"action": "benchmark", "args": {"model": "qwen2.5:1.5b"}})
        items = lab.changes()["changes"]
        self.assertEqual([c["kind"] for c in items], ["check", "check"])
        self.assertIn("22.4 tokens/s", items[1]["what"])
        self.assertTrue(all(c["undo_model"] is None for c in items))

    def test_assistant_activity_names_tools_but_never_the_message(self):
        class Fake:
            messages = []

            def ask(self, text):
                from telemetry_agent.agent import AgentReply
                return AgentReply("Done.", trace=[{"tool": "check_install", "args": {}, "result": {}, "chosen_by": "llm"}])
        lab = self._temp_lab()
        lab._agents["qwen2.5:1.5b"] = Fake()
        with mock.patch.object(lab, "runtime_state", return_value={"lab_models": ["qwen2.5:1.5b"]}), \
             mock.patch.object(lab.tools, "ensure_model_ready", return_value={}):
            lab.chat("private question about my thesis")
        logged = json.dumps(lab.changes())
        self.assertIn("check_install", logged)
        self.assertNotIn("thesis", logged)

    def test_approving_measure_really_measures(self):
        """Approval gates the assistant's tool, not the job the learner just approved."""
        with mock.patch.object(self.lab.tools, "ensure_model_ready", return_value={}), \
                mock.patch("telemetry_agent.tools.ChatClient") as client, \
                mock.patch("telemetry_agent.tools.collector.run_benchmark",
                           return_value={"median_tps": 40.0, "peak_ram_mb": 900.0}) as run:
            client.return_value.metadata.return_value = {"other_models_resident": []}
            out = self.lab._do_benchmark({"log": []}, "qwen2.5:1.5b")
        run.assert_called_once()
        self.assertNotIn("proposed", out)
        self.assertEqual(out["median_tps"], 40.0)

    def test_an_invented_model_name_is_not_reported_as_missing(self):
        from telemetry_agent.tools import Toolbox
        box = Toolbox(Settings(base_url="http://127.0.0.1:9/v1", approval_required=True))
        out = box.check_install(model="any")
        self.assertNotIn("any is not installed", json.dumps(out))

    def test_nothing_runs_from_chat_without_a_card(self):
        from telemetry_agent.tools import Toolbox
        box = Toolbox(Settings(base_url="http://127.0.0.1:9/v1", approval_required=True))
        with mock.patch.object(box, "ensure_model_ready") as ready:
            out = box.run_benchmark("qwen2.5:1.5b", guess_tps=30)
            ready.assert_not_called()
        self.assertEqual(out["proposed"], {"action": "benchmark", "args": {"model": "qwen2.5:1.5b", "repeats": 3, "guess_tps": 30}})
        self.assertLessEqual(len(box.check_install(5)["steps"]), 4)  # the fifth check loads the model: that is a card now
        self.assertEqual(box.propose_step("pull_model", "qwen2.5:1.5b")["proposed"], {"action": "pull_model", "args": {"model": "qwen2.5:1.5b"}})
        self.assertEqual(box.propose_step("check_install", "qwen2.5:1.5b")["proposed"]["args"], {"model": "qwen2.5:1.5b", "up_to_step": 4})
        for step, model in (("install_runtime", "qwen2.5:1.5b"), ("rm -rf", "qwen2.5:1.5b"), ("pull_model", "evil/model"), ("pull_model", "llama3:latest")):
            with self.assertRaises(ValueError):
                box.propose_step(step, model)
        # The helper turns a proposal into the same card the plan uses, and the page gets it with the reply.
        from telemetry_agent.agent import AgentReply

        class Proposer:
            messages = []

            def ask(self, text):
                return AgentReply("Approve the card below.", trace=[{"tool": "run_benchmark", "args": {"model": "qwen2.5:1.5b"},
                                  "result": {"proposed": {"action": "benchmark", "args": {"model": "qwen2.5:1.5b", "repeats": 3}}}, "chosen_by": "router"}])
        lab = self._temp_lab()
        lab._agents["qwen2.5:1.5b"] = Proposer()
        with mock.patch.object(lab, "runtime_state", return_value={"lab_models": ["qwen2.5:1.5b"], "models": ["qwen2.5:1.5b"], "installed": True, "running": True}), \
             mock.patch.object(lab.tools, "ensure_model_ready", return_value={}):
            answer = lab.chat("how fast is qwen2.5:1.5b?")
        self.assertEqual([(c["title"], c["action"], c["args"]) for c in answer["proposals"]],
                         [("Measure qwen2.5:1.5b", "benchmark", {"model": "qwen2.5:1.5b", "repeats": 3})])
        self.assertTrue(answer["proposals"][0]["why"] and answer["proposals"][0]["does"])

    def test_plan_comes_from_the_registry_and_every_command_is_registered(self):
        from telemetry_agent import actions
        lab = self._temp_lab()
        state = {"installed": True, "running": False, "models": ["qwen2.5:1.5b"], "lab_models": ["qwen2.5:1.5b"]}
        with mock.patch.object(lab, "runtime_state", return_value=state):
            steps = lab.plan("qwen2.5:1.5b")["steps"]
        self.assertEqual([s["id"] for s in steps], ["install_runtime", "start_runtime", "pull_model", "verify_install", "first_prompt"])
        self.assertEqual([s["done"] for s in steps], [True, False, True, False, False])
        registered = actions.registered_commands()
        for step in steps:
            if step["command"] and step["command"] != "Start menu > Ollama":
                self.assertIn(step["command"], registered, step["id"])
            for key in ("what", "why", "does"):
                self.assertTrue(step[key], f"{step['id']} has no {key}")
        # The shown start command is the one the executor will use: the app if present, else the CLI server.
        with mock.patch.object(actions, "ollama_app", return_value="/Applications/Ollama.app"):
            self.assertEqual(actions.runtime_context(None, state)["start"], "open -a Ollama")
        with mock.patch.object(actions, "ollama_app", return_value="/opt/homebrew/bin/ollama"):
            self.assertEqual(actions.runtime_context(None, state)["start"], "ollama serve")
        card = lab.describe_action("benchmark", {"model": "qwen2.5:1.5b", "repeats": 3})
        self.assertEqual((card["title"], card["args"]["model"], card["how"]), ("Measure qwen2.5:1.5b", "qwen2.5:1.5b", "api"))

    def test_verify_step_checks_the_chosen_model_not_any_model(self):
        lab = self._temp_lab()
        self.assertEqual(lab.plan("qwen2.5:3b")["steps"][3]["args"], {"up_to_step": 4, "model": "qwen2.5:3b"})
        with mock.patch.object(lab.tools, "check_install", return_value={"steps": [{"ok": True, "detail": "x"}]}) as check:
            lab._do_check_install({"log": []}, up_to_step=4, model="qwen2.5:3b")
            check.assert_called_once_with(4, "qwen2.5:3b")
        with self.assertRaises(helper.BadRequest):  # a model that isn't on the allow-list is refused
            lab.start_job("check_install", {"up_to_step": 4, "model": "evil/model"})

    def test_safe_text_hides_local_paths_but_keeps_links(self):
        self.assertEqual(helper._safe_text("see https://ollama.com/download and C:\\Users\\me\\x and /Users/me/y"),
                         "see https://ollama.com/download and [local path omitted] and [local path omitted]")

    def test_chat_falls_back_to_rules_when_the_model_does_not_answer(self):
        from telemetry_agent.llm import LLMError

        class Broken:
            messages = []

            def ask(self, text):
                raise LLMError("down")
        lab = self._temp_lab()
        lab._agents["qwen2.5:1.5b"] = Broken()
        with mock.patch.object(lab, "runtime_state", return_value={"lab_models": ["qwen2.5:1.5b"], "models": ["qwen2.5:1.5b"]}), \
             mock.patch.object(lab.tools, "ensure_model_ready", return_value={}):
            answer = lab.chat("Tell me a story about a boat")
        self.assertEqual((answer["mode"], answer["retry"]), ("rule_only", True))
        self.assertIn("isn't available", answer["text"])
        Broken.ask = lambda self, text: (_ for _ in ()).throw(LLMError('Local runtime returned HTTP 404: model "qwen2.5:1.5b" not found, try pulling it first.'))
        with mock.patch.object(lab, "runtime_state", return_value={"lab_models": ["qwen2.5:1.5b"], "models": ["qwen2.5:1.5b"]}), \
             mock.patch.object(lab.tools, "ensure_model_ready", return_value={}):
            answer = lab.chat("Tell me a story about a boat")
        self.assertIn("not found, try pulling it first", answer["text"])
        self.assertIn("pull", answer["text"].lower())

    def test_show_model_only_opens_a_real_model_file_of_a_downloaded_model(self):
        lab = self._temp_lab()
        blobs = Path(lab.settings.results_dir) / "blobs"
        blobs.mkdir()
        blob = blobs / ("sha256-" + "a" * 64)
        blob.write_bytes(b"x" * 1024)
        state = {"lab_models": ["qwen2.5:1.5b"]}
        with mock.patch.object(lab, "runtime_state", return_value=state), mock.patch.object(helper, "_reveal") as reveal, \
             mock.patch.object(helper.ChatClient, "model_file", return_value=str(blob)):
            shown = lab.show_model("qwen2.5:1.5b")
            reveal.assert_called_once_with(blob)
            self.assertEqual((shown["path"], shown["opened"]), (str(blob), True))
            self.assertNotIn(str(blob), json.dumps(lab.changes()))
            reveal.reset_mock()
            for bad in ("/etc/passwd", "../evil", "/Applications/Calculator.app"):
                with mock.patch.object(helper.ChatClient, "model_file", return_value=bad), self.assertRaises(helper.BadRequest):
                    lab.show_model("qwen2.5:1.5b")
            for model in ("qwen2.5:3b", "/etc/passwd", None):  # not downloaded, or not on the allow-list
                with self.assertRaises(helper.BadRequest):
                    lab.show_model(model)
            reveal.assert_not_called()
            reveal.side_effect = OSError("no file manager")
            self.assertFalse(lab.show_model("qwen2.5:1.5b")["opened"])  # the path is still shown

    def test_a_listed_model_whose_file_is_gone_is_not_installed(self):
        """Ollama keeps a model in its list after its file vanishes; the lab must not call that installed."""
        lab = self._temp_lab()
        blobs = Path(lab.settings.results_dir) / "blobs"
        blobs.mkdir()
        present = blobs / ("sha256-" + "b" * 64)
        present.write_bytes(b"x" * 1024)
        files = {"qwen2.5:3b": str(present), "qwen2.5:1.5b": str(blobs / ("sha256-" + "c" * 64)), "llama3.2:1b": None,
                 "qwen2.5:7b": helper.LLMError("Local runtime returned HTTP 404: model 'qwen2.5:7b' not found.")}

        def model_file(self_, tag):
            if files[tag] is None:
                raise helper.LLMError("The local model server could not be reached or timed out.")  # couldn't say: trust the list
            if isinstance(files[tag], Exception):
                raise files[tag]  # listed, yet "not found": Ollama's own sign that the files are gone
            return files[tag]

        with mock.patch.object(helper.ChatClient, "list_models", return_value=list(files)), \
             mock.patch.object(helper.ChatClient, "model_file", model_file):
            rt = lab.runtime_state()
            self.assertEqual(rt["broken_models"], ["qwen2.5:1.5b", "qwen2.5:7b"])
            self.assertEqual(rt["models"], ["qwen2.5:3b", "llama3.2:1b"])
            self.assertNotIn("qwen2.5:1.5b", rt["lab_models"])
            self.assertEqual(rt["models_dir"], str(lab.settings.runtime_models_dir))
            with mock.patch.object(lab.tools, "check_hardware", return_value={"available_ram_gb": 8, "total_ram_gb": 16, "free_disk_gb": 50}):
                rows = {m["name"]: m for m in lab.compatibility()["models"]}
            self.assertFalse(rows["qwen2.5:1.5b"]["installed"])
            self.assertTrue(rows["qwen2.5:1.5b"]["missing_file"])
            self.assertTrue(rows["qwen2.5:3b"]["installed"])
            pull = next(s for s in lab.plan("qwen2.5:1.5b")["steps"] if s["id"] == "pull_model")
            self.assertFalse(pull["done"])
            self.assertIn("missing", pull["why"])

    def test_apps_are_a_second_provider_with_the_same_cards_log_and_undo(self):
        """Installing an app runs exactly the command its card showed, is logged with undo, and only listed apps are allowed."""
        from telemetry_agent import apps as appmod
        lab = self._temp_lab()
        present = {"vscode": None}
        brew = {"name": "Homebrew", "cli": "brew", "installed": True, "link": "https://brew.sh", "note": ""}
        with mock.patch.object(appmod, "manager", return_value=brew), mock.patch.object(helper, "app_manager", return_value=brew), \
             mock.patch.object(appmod, "app_path", side_effect=lambda app: present.get(app["id"])), \
             mock.patch.object(helper, "app_path", side_effect=lambda app: present.get(app["id"])), \
             mock.patch.object(appmod.platform, "system", return_value="Darwin"), \
             mock.patch.object(helper.platform, "system", return_value="Darwin"):
            plan = lab.plan_app("vscode")
            self.assertEqual([s["id"] for s in plan["steps"]], ["install_app", "check_app"])
            install = plan["steps"][0]
            self.assertEqual(install["command"], "brew install --cask visual-studio-code")
            self.assertIn("never needs your password", install["does"])
            self.assertFalse(install["done"])
            with self.assertRaises(helper.BadRequest):
                lab.plan_app("zoom")
            with self.assertRaises(helper.BadRequest):
                lab.start_job("install_app", {"app": "zoom"})
            with self.assertRaises(helper.BadRequest):
                lab.start_job("install_app", {"app": "vscode", "extra": 1})

            ran = []

            def fake_run(job, command, timeout=900):
                ran.append(command)
                job["log"].append("==> Installing Cask visual-studio-code")
                present["vscode"] = Path("/Applications/Visual Studio Code.app")
            job = {"action": "install_app", "args": {"app": "vscode"}, "log": [], "status": "running"}
            lab._operation_lock.acquire()
            with mock.patch.object(lab, "_run_command", side_effect=fake_run):
                lab._run_job(job)
            self.assertEqual(job["status"], "done", job.get("error"))
            self.assertEqual(ran, [install["command"]])  # the command shown is the command run
            self.assertTrue(job["result"]["installed"])
            logged = [c for c in lab.changes()["changes"] if c.get("undo_app") == "vscode"]
            self.assertEqual(len(logged), 1)
            self.assertIn("Installed Visual Studio Code with Homebrew", logged[0]["what"])
            self.assertTrue(lab.apps()["apps"][0]["by_lab"])
            self.assertTrue(lab.plan_app("vscode")["steps"][0]["done"])

            # Undo runs the remove command shown, verifies the app is gone, and marks the log entry undone.
            def fake_remove(job, command, timeout=900):
                ran.append(command)
                present["vscode"] = None
            job = {"action": "remove_app", "args": {"app": "vscode"}, "log": [], "status": "running"}
            lab._operation_lock.acquire()
            with mock.patch.object(lab, "_run_command", side_effect=fake_remove):
                lab._run_job(job)
            self.assertEqual(job["status"], "done", job.get("error"))
            self.assertEqual(ran[-1], "brew uninstall --cask visual-studio-code")
            self.assertTrue(all(c["undone"] for c in lab.changes()["changes"] if c.get("undo_app") == "vscode"))
            self.assertFalse(lab.apps()["apps"][0]["by_lab"])
            # Nothing the lab didn't install can be removed here.
            job = {"action": "remove_app", "args": {"app": "obsidian"}, "log": [], "status": "running"}
            lab._operation_lock.acquire()
            lab._run_job(job)
            self.assertEqual(job["status"], "failed")

    def test_without_a_package_manager_the_app_step_is_manual(self):
        from telemetry_agent import apps as appmod
        lab = self._temp_lab()
        none = {"name": "Homebrew", "cli": "brew", "installed": False, "link": "https://brew.sh", "note": ""}
        with mock.patch.object(appmod, "manager", return_value=none), mock.patch.object(appmod, "app_path", return_value=None), \
             mock.patch.object(appmod.platform, "system", return_value="Darwin"):
            steps = lab.plan_app("obsidian")["steps"]
            self.assertEqual((steps[0]["kind"], steps[0]["action"], steps[0]["link"]), ("manual", None, "https://obsidian.md/download"))
            self.assertIn("admin password, stop", steps[0]["does"])

    def test_receipt_lists_what_was_added_and_how_to_undo_it(self):
        lab = self._temp_lab()
        blobs = Path(lab.settings.results_dir) / "blobs"
        blobs.mkdir()
        blob = blobs / ("sha256-" + "d" * 64)
        blob.write_bytes(b"x" * 2048)
        lab._log_change("Downloaded qwen2.5:1.5b, about 1.1 GB, to Ollama's models folder.", undo_model="qwen2.5:1.5b")
        lab._log_change("Installed Visual Studio Code with Homebrew, about 0.5 GB, in the Applications folder.", undo_app="vscode")
        lab._log_change("Checked your laptop.", kind="check")
        rt = {"lab_models": ["qwen2.5:1.5b"], "models": ["qwen2.5:1.5b"], "broken_models": ["qwen2.5:7b"], "installed": True, "running": True,
              "models_dir": str(blobs.parent), "models_dir_exists": True}
        with mock.patch.object(lab, "runtime_state", return_value=rt), mock.patch.object(helper.ChatClient, "model_file", return_value=str(blob)), \
             mock.patch.object(helper, "app_path", return_value=Path("/Applications/Visual Studio Code.app")), \
             mock.patch.object(helper.platform, "system", return_value="Darwin"):
            out = lab.receipt()
        text = out["markdown"]
        self.assertTrue(out["filename"].endswith(".md"))
        for needle in ("# Local AI Lab receipt", "**qwen2.5:1.5b**", str(blob), "(downloaded by this lab)", "`ollama rm qwen2.5:1.5b`",
                       "**Visual Studio Code**", "Visual Studio Code.app", "brew uninstall --cask visual-studio-code",
                       "qwen2.5:7b", "2 steps changed this laptop, 1 only read or measured", "never asked for your password"):
            self.assertIn(needle, text)

    def test_show_models_folder_opens_only_the_configured_folder(self):
        lab = self._temp_lab()
        folder = Path(lab.settings.results_dir) / "ollama-models"
        with mock.patch.object(helper, "_open_folder") as opened:
            lab.settings = dataclasses.replace(lab.settings, runtime_models_dir=folder)
            with self.assertRaises(helper.BadRequest):
                lab.show_models_folder()  # not created yet
            opened.assert_not_called()
            folder.mkdir()
            shown = lab.show_models_folder()
            opened.assert_called_once_with(folder)
            self.assertEqual((shown["folder"], shown["opened"]), (str(folder), True))
            self.assertIn("models folder", json.dumps(lab.changes()))
            self.assertNotIn(str(folder), json.dumps(lab.changes()))
            opened.side_effect = OSError("no file manager")
            self.assertFalse(lab.show_models_folder()["opened"])

    def test_undo_only_removes_a_model_this_lab_logged(self):
        lab = self._temp_lab()
        with mock.patch.object(helper.ChatClient, "delete_model") as delete:
            with self.assertRaisesRegex(RuntimeError, "Only a model this lab downloaded"):
                lab._do_remove_model({"log": []}, "qwen2.5:3b")
            delete.assert_not_called()
            lab._log_change("Downloaded qwen2.5:3b", undo_model="qwen2.5:3b")
            lab._do_remove_model({"log": []}, "qwen2.5:3b")
            delete.assert_called_once_with("qwen2.5:3b")
            with self.assertRaisesRegex(RuntimeError, "Only a model this lab downloaded"):
                lab._do_remove_model({"log": []}, "qwen2.5:3b")
        self.assertTrue(lab.changes()["changes"][0]["undone"])

    def test_pull_logs_only_a_new_model_and_stops_on_error(self):
        lab = self._temp_lab()
        state = {"non_model_gib": 0.5}
        rt = {"models": [], "lab_models": [], "running": True, "installed": True}
        progress = [{"status": "pulling abc", "total": 10, "completed": 5}, {"status": "success"}]
        with mock.patch.object(lab.tools, "budget_state", return_value=state), \
             mock.patch.object(lab, "runtime_state", return_value=rt), \
             mock.patch.object(helper.ChatClient, "pull_stream", return_value=iter(progress)):
            job = {"log": []}
            lab._do_pull_model(job, "qwen2.5:0.5b")
        self.assertEqual(job["progress"], 0.5)
        self.assertEqual(lab.changes()["changes"][0]["undo_model"], "qwen2.5:0.5b")
        with mock.patch.object(lab.tools, "budget_state", return_value=state), \
             mock.patch.object(lab, "runtime_state", return_value={**rt, "models": ["qwen2.5:0.5b"]}), \
             mock.patch.object(helper.ChatClient, "pull_stream") as download:
            result = lab._do_pull_model({"log": []}, "qwen2.5:0.5b")
            download.assert_not_called()
            self.assertFalse(result["downloaded"])
        self.assertEqual(len(lab.changes()["changes"]), 1)
        with mock.patch.object(lab.tools, "budget_state", return_value=state), \
             mock.patch.object(lab, "runtime_state", return_value=rt), \
             mock.patch.object(helper.ChatClient, "pull_stream", return_value=iter([{"error": "pull failed"}])), \
             self.assertRaisesRegex(RuntimeError, "pull failed"):
            lab._do_pull_model({"log": []}, "qwen2.5:0.5b")

    def test_assistant_gives_a_labelled_rule_answer_when_the_model_cannot_run(self):
        lab = self._temp_lab()
        with mock.patch.object(lab, "runtime_state", return_value={"lab_models": ["qwen2.5:1.5b"], "models": []}), \
             mock.patch.object(lab.tools, "ensure_model_ready", side_effect=ValueError("Not enough memory right now.")):
            answer = lab.chat("Tell me a story about a boat")
        self.assertEqual(answer["mode"], "rule_only")
        self.assertIn("Not enough memory", answer["text"])

    def test_chat_model_prefers_one_that_can_tutor(self):
        self.assertEqual(self.lab._agent_model(["qwen2.5:0.5b", "qwen2.5:1.5b", "qwen2.5:7b"]), "qwen2.5:1.5b")
        self.assertEqual(self.lab._agent_model(["qwen2.5:0.5b"]), "qwen2.5:0.5b")

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
        with self.assertRaises(helper.BadRequest):
            self.lab.try_model("qwen2.5:0.5b", "Say something", 999)

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
