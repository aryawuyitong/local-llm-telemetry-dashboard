import json
import unittest

from telemetry_agent.agent import LabAgent
from telemetry_agent.config import Settings


class FakeLLM:
    """Replays scripted assistant messages and records what it was sent."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def chat(self, messages, tools=None, **kw):
        self.calls.append({"messages": [dict(m) for m in messages], "tools": tools})
        return self.replies.pop(0)


def tool_call(name, args):
    return {"content": "", "tool_calls": [{"id": "c1", "type": "function",
                                           "function": {"name": name, "arguments": json.dumps(args)}}]}


class AgentLoop(unittest.TestCase):
    def test_calls_read_logs_then_answers(self):
        llm = FakeLLM([tool_call("read_logs", {"log_text": "No space left on device"}),
                       {"content": "Your disk is full. Pick a smaller model."}])
        reply = LabAgent(Settings(), llm=llm).ask("Download failed: No space left on device")
        self.assertEqual(reply.trace[0]["tool"], "read_logs")
        self.assertEqual(reply.trace[0]["result"]["matches"][0]["id"], "disk_full")
        self.assertIn("smaller model", reply.text)
        tool_msg = llm.calls[1]["messages"][-1]
        self.assertEqual(tool_msg["role"], "tool")

    def test_understands_json_tool_call_written_as_text(self):
        llm = FakeLLM([{"content": '<tool_call>{"name": "read_logs", "arguments": {"log_text": "address already in use"}}</tool_call>'},
                       {"content": "Another server is using that port."}])
        reply = LabAgent(Settings(), llm=llm).ask("server won't start")
        self.assertEqual(reply.trace[0]["result"]["matches"][0]["id"], "port_in_use")

    def test_guardrail_asks_for_rewrite(self):
        llm = FakeLLM([{"content": "Run `sudo pip install psutil`."},
                       {"content": "Run `python3 -m pip install --user psutil`."}])
        reply = LabAgent(Settings(guardrails=True), llm=llm).ask("pip says permission denied")
        self.assertTrue(reply.guardrail_intervened)
        self.assertNotIn("sudo", reply.text)
        self.assertEqual({v.rule for v in reply.raw_violations}, {"admin"})

    def test_guardrail_scrubs_if_rewrite_is_still_unsafe(self):
        llm = FakeLLM([{"content": "`rm -rf models`"}, {"content": "Try `rm -rf models` again"}])
        reply = LabAgent(Settings(guardrails=True), llm=llm).ask("wipe my models")
        self.assertNotIn("rm -rf", reply.text)
        self.assertIn("removed by safety guardrail", reply.text)

    def test_no_guardrails_passes_text_through(self):
        llm = FakeLLM([{"content": "Run `sudo pip install psutil`."}])
        agent = LabAgent(Settings(guardrails=False), llm=llm)
        reply = agent.ask("pip says permission denied")
        self.assertIn("sudo", reply.text)
        self.assertFalse(reply.guardrail_intervened)
        self.assertNotIn("Safety rules", agent.messages[0]["content"])

    def test_secrets_are_redacted_before_reaching_the_llm(self):
        llm = FakeLLM([{"content": "Please revoke that token."}])
        LabAgent(Settings(guardrails=True), llm=llm).ask("my token is hf_AbCdEfGhIjKlMnOpQrStUvWxYz123456")
        sent = llm.calls[0]["messages"][-1]["content"]
        self.assertNotIn("hf_AbCd", sent)

    def test_stops_after_max_steps(self):
        loop = [tool_call("check_hardware", {})] * 3 + [{"content": "Here is the summary."}]
        reply = LabAgent(Settings(max_steps=3, router=False), llm=FakeLLM(loop)).ask("what can my laptop run?")
        self.assertEqual(len(reply.trace), 3)
        self.assertEqual(reply.text, "Here is the summary.")


class Router(unittest.TestCase):
    def test_router_runs_read_logs_before_the_llm(self):
        llm = FakeLLM([{"content": "Another server is using port 8080; start on --port 8081."}])
        reply = LabAgent(Settings(), llm=llm).ask("got: address already in use on 127.0.0.1:8080")
        self.assertEqual(reply.trace[0]["chosen_by"], "router")
        self.assertEqual(reply.trace[0]["result"]["matches"][0]["id"], "port_in_use")
        self.assertEqual(llm.calls[0]["messages"][-1]["role"], "tool")  # LLM sees the result first

    def test_router_off_leaves_choice_to_llm(self):
        llm = FakeLLM([{"content": "ok"}])
        reply = LabAgent(Settings(router=False), llm=llm).ask("got: address already in use")
        self.assertEqual(reply.trace, [])


class RouteRules(unittest.TestCase):
    names = ["qwen2.5:3b", "qwen2.5:1.5b", "phi3.5"]

    def test_routes(self):
        from telemetry_agent.router import route
        cases = {
            "Traceback ... Permission denied": ("read_logs", None),
            "Can you test how fast qwen2.5:1.5b is? I guess 30 tokens per second and 2 GB of RAM":
                ("run_benchmark", {"model": "qwen2.5:1.5b", "guess_tps": 30.0, "guess_ram_gb": 2.0}),
            "Which model should I download?": ("recommend_model", {}),
            "What's next? Did I install it right?": ("check_install", {}),
            "How much RAM does my laptop have?": ("check_hardware", {}),
            "What is quantization?": None,
        }
        for text, want in cases.items():
            with self.subTest(text=text):
                got = route(text, self.names)
                if want is None:
                    self.assertEqual(got, [])
                else:
                    self.assertEqual(got[0][0], want[0])
                    if want[1] is not None:
                        self.assertEqual(got[0][1], want[1])

    def test_catalog_errors_without_error_words_still_route(self):
        from telemetry_agent.router import route
        self.assertEqual(route("zsh: bad CPU type in executable", self.names), [])
        got = route("zsh: bad CPU type in executable", self.names, is_known_error=lambda t: True)
        self.assertEqual(got[0][0], "read_logs")

    def test_does_not_confuse_similar_model_names(self):
        from telemetry_agent.router import route
        self.assertEqual(route("benchmark qwen2.5:3b please", self.names)[0][1]["model"], "qwen2.5:3b")


if __name__ == "__main__":
    unittest.main()
