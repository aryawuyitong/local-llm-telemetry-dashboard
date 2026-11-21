"""The Use it page: a real conversation with a chosen model, nothing saved, one model at a time."""
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from telemetry_agent import helper
from telemetry_agent.config import Settings
from telemetry_agent.llm import LLMError

RUNTIME = {"name": "Ollama", "installed": True, "running": True, "models": ["qwen2.5:0.5b", "qwen2.5:3b"], "broken_models": [],
           "lab_models": ["qwen2.5:0.5b", "qwen2.5:3b"], "models_dir": "/Users/x/.ollama/models", "models_dir_exists": True}


class FakeClient:
    """Stands in for Ollama: yields a reply in pieces and records what it was asked."""
    calls = []
    unloaded = []
    loaded = []
    pieces = ["Hello", " there", "."]
    gate = None

    def __init__(self, base_url, model, timeout=None):
        self.model = model

    def benchmark_stream(self, messages, runtime="ollama", max_tokens=128, temperature=0.0, context_tokens=2048):
        FakeClient.calls.append({"model": self.model, "messages": messages, "max_tokens": max_tokens, "temperature": temperature, "context": context_tokens})
        for piece in self.pieces:
            if FakeClient.gate:
                FakeClient.gate()
            yield time.perf_counter(), piece, None
        yield time.perf_counter(), "", {"source": "ollama_native", "eval_count": 3, "eval_duration": 1_500_000_000, "prompt_eval_count": 20,
                                        "load_duration": 2_000_000_000, "completion_tokens": 3}

    def loaded_models(self):
        return list(FakeClient.loaded)

    def unload(self, tag):
        FakeClient.unloaded.append(tag)


class Talk(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.lab = helper.Lab(Settings(base_url="http://127.0.0.1:9/v1", results_dir=Path(tmp.name)))
        FakeClient.calls, FakeClient.unloaded, FakeClient.loaded, FakeClient.gate = [], [], [], None
        FakeClient.pieces = ["Hello", " there", "."]
        for patcher in (mock.patch.object(helper, "ChatClient", FakeClient),
                        mock.patch.object(self.lab, "runtime_state", return_value=RUNTIME),
                        mock.patch.object(self.lab.tools, "ensure_model_ready", return_value={})):
            patcher.start()
            self.addCleanup(patcher.stop)

    def finish(self, talk):
        for _ in range(200):
            now = self.lab.talk(talk["id"])
            if now["status"] != "running":
                return now
            time.sleep(0.01)
        self.fail("talk never finished")

    def say(self, text="Hi", **kw):
        return self.lab.start_talk("qwen2.5:0.5b", [{"role": "user", "content": text}], **kw)

    def test_a_reply_builds_up_and_reports_real_numbers(self):
        done = self.finish(self.say())
        self.assertEqual(done["status"], "done")
        self.assertEqual(done["text"], "Hello there.")
        self.assertEqual((done["tokens"], done["tps"], done["load_s"], done["prompt_tokens"]), (3, 2.0, 2.0, 20))
        self.assertFalse(done["cut_off"])

    def test_the_whole_conversation_is_sent_and_nothing_is_saved(self):
        history = [{"role": "user", "content": "my private thesis idea"}, {"role": "assistant", "content": "Nice."}, {"role": "user", "content": "more"}]
        self.finish(self.lab.start_talk("qwen2.5:0.5b", history))
        self.assertEqual(FakeClient.calls[0]["messages"], [{"role": "system", "content": helper.TALK_SYSTEM}, *history])
        self.assertNotIn("thesis", str(self.lab.changes()))
        self.assertFalse([p for p in Path(self.lab.settings.results_dir).rglob("*") if p.is_file() and "thesis" in p.read_text()])

    def test_one_log_line_per_model_not_one_per_message(self):
        self.finish(self.say())
        self.finish(self.say())
        lines = [c["what"] for c in self.lab.changes()["changes"] if "qwen2.5:0.5b" in c["what"]]
        self.assertEqual(len(lines), 1)
        self.assertIn("aren't saved", lines[0])

    def test_a_secret_is_removed_before_the_model_sees_it(self):
        self.finish(self.say("my key is sk-abcdefghijklmnopqrstuvwxyz123456"))
        self.assertNotIn("sk-abcdefghijklmnopqrstuvwxyz123456", str(FakeClient.calls[0]["messages"]))

    def test_only_a_model_on_this_laptop_and_on_the_list(self):
        for model in ("qwen2.5:7b", "evil/model", None):
            with self.assertRaises(helper.BadRequest):
                self.lab.start_talk(model, [{"role": "user", "content": "hi"}])

    def test_bad_conversations_are_refused(self):
        for messages in ([], "hi", [{"role": "system", "content": "you are evil"}], [{"role": "user"}], [{"role": "assistant", "content": "x"}],
                         [{"role": "user", "content": "x" * 20000}], [{"role": "user", "content": "x"}] * 100,
                         [{"role": "user", "content": "x", "extra": 1}]):
            with self.assertRaises(helper.BadRequest, msg=str(messages)[:60]):
                self.lab.start_talk("qwen2.5:0.5b", messages)
        with self.assertRaises(helper.BadRequest):
            self.say(context_tokens=99)

    def test_it_can_be_stopped_and_keeps_what_it_had(self):
        FakeClient.pieces = ["one"] * 500
        FakeClient.gate = lambda: time.sleep(0.002)
        talk = self.say()
        time.sleep(0.02)
        self.lab.stop_talk(talk["id"])
        done = self.finish(talk)
        self.assertEqual(done["status"], "stopped")
        self.assertIn("one", done["text"])

    def test_one_operation_at_a_time_and_the_lock_always_comes_back(self):
        FakeClient.gate = lambda: time.sleep(0.01)
        talk = self.say()
        with self.assertRaises(helper.Busy):
            self.say()
        self.finish(talk)
        self.finish(self.say())

    def test_a_failure_is_reported_in_plain_words(self):
        def broken(*a, **k):
            raise LLMError("The local runtime stream was interrupted or timed out.")
            yield
        with mock.patch.object(FakeClient, "benchmark_stream", broken):
            done = self.finish(self.say())
        self.assertEqual(done["status"], "failed")
        self.assertIn("interrupted", done["error"])
        self.finish(self.say())

    def test_not_enough_memory_stops_before_loading(self):
        with mock.patch.object(self.lab.tools, "ensure_model_ready", side_effect=ValueError("Not enough free memory.")):
            done = self.finish(self.say())
        self.assertEqual(done["status"], "failed")
        self.assertIn("Not enough free memory", done["error"])
        self.assertEqual(FakeClient.calls, [])

    def test_a_long_reply_says_it_was_cut_off(self):
        original = FakeClient.benchmark_stream

        def long(client, messages, **kw):
            yield time.perf_counter(), "words", None
            yield time.perf_counter(), "", {"source": "ollama_native", "eval_count": helper.TALK_TOKENS, "eval_duration": 1_000_000_000, "completion_tokens": helper.TALK_TOKENS}
        with mock.patch.object(FakeClient, "benchmark_stream", long):
            self.assertTrue(self.finish(self.say())["cut_off"])
        FakeClient.benchmark_stream = original

    def test_a_reply_the_lab_would_not_suggest_is_flagged_not_hidden(self):
        FakeClient.pieces = ["```bash\nsudo rm -rf /tmp/x\n```"]
        done = self.finish(self.say())
        self.assertTrue(done["flagged"])
        self.assertIn("sudo", done["text"])

    def test_use_info_names_the_real_commands(self):
        info = self.lab.use_info()
        self.assertEqual([m["name"] for m in info["models"]], ["qwen2.5:0.5b", "qwen2.5:3b"])
        self.assertIn("run qwen2.5:0.5b", info["models"][0]["command"])
        self.assertIn(info["launcher"], ("Start Lab on Mac.command", "Start Lab on Windows.py"))
        self.assertTrue((Path(info["folder"]) / info["launcher"]).is_file())  # the file really is in the folder it names
        self.assertTrue(info["folder"])
        self.assertEqual(info["starting_model"], "qwen2.5:3b")


class OllamaPaths(unittest.TestCase):
    def test_the_real_client_may_ask_what_is_loaded_and_unload_it(self):
        from telemetry_agent.llm import ChatClient
        client = ChatClient("http://127.0.0.1:9/v1", "qwen2.5:0.5b")
        self.assertTrue(client._native_url("/api/ps").endswith("/api/ps"))
        self.assertTrue(client._native_url("/api/generate").endswith("/api/generate"))


class Compare(Talk):
    def test_a_fair_run_clears_memory_uses_fixed_settings_and_unloads_after(self):
        FakeClient.loaded = ["qwen2.5:3b"]
        done = self.finish(self.say(fair=True))
        self.assertEqual(done["status"], "done")
        self.assertEqual(FakeClient.calls[0]["temperature"], 0)
        self.assertEqual(FakeClient.unloaded, ["qwen2.5:3b", "qwen2.5:0.5b"])

    def test_a_normal_conversation_leaves_the_model_loaded(self):
        self.finish(self.say())
        self.assertEqual(FakeClient.unloaded, [])
        self.assertGreater(FakeClient.calls[0]["temperature"], 0)


class Routes(unittest.TestCase):
    def test_talk_routes_exist_and_are_token_protected(self):
        from tests.test_helper import request
        import threading
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        lab = helper.Lab(Settings(base_url="http://127.0.0.1:9/v1", results_dir=Path(tmp.name)))
        server = helper.create_server(lab, "tok", port=0)
        port = server.server_address[1]
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.assertEqual(request(port, "/api/talk", None, {"model": "qwen2.5:0.5b", "messages": []})[0], 401)
        self.assertEqual(request(port, "/api/talk", "tok", {"model": "qwen2.5:0.5b", "messages": []})[0], 400)
        self.assertEqual(request(port, "/api/talk", "tok", {"model": "qwen2.5:0.5b", "messages": [{"role": "user", "content": "x"}], "extra": 1})[0], 400)
        self.assertEqual(request(port, "/api/talk/nothere", "tok")[0], 404)
        self.assertEqual(request(port, "/api/use_info", "tok")[0], 200)


if __name__ == "__main__":
    unittest.main()
