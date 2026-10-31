"""Malformed model output must never turn into a default/no-argument action."""
import json
import math
import unittest
from unittest import mock

from telemetry_agent.agent import LabAgent, MAX_CALLS_PER_REPLY, MAX_TOOL_ARGUMENT_CHARS, _tool_calls
from telemetry_agent.config import Settings


class FakeLLM:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.received = []

    def chat(self, messages, **kwargs):
        self.received.append([dict(item) for item in messages])
        return next(self.replies)


class RecordingTools:
    allow_list = [{"ollama_tag": "qwen2.5:1.5b"}]

    def __init__(self):
        self.executed = []

    def schemas(self):
        return [{"function": {"name": name}} for name in ("check_hardware", "read_logs")]

    def call(self, name, args):
        self.executed.append((name, args))
        return {"observed": True}


def native(arguments, name="check_hardware"):
    return {"content": None, "tool_calls": [{"id": "model-call", "type": "function",
                                             "function": {"name": name, "arguments": arguments}}]}


class Boundaries(unittest.TestCase):
    def _run(self, message):
        tools = RecordingTools()
        llm = FakeLLM([message, {"content": "Please correct the request and retry."}])
        with mock.patch("telemetry_agent.agent.hardware_info", return_value={"os": "test", "os_version": "test", "arch": "x64"}):
            agent = LabAgent(Settings(router=False), llm=llm, toolbox=tools)
            reply = agent.ask("A generic question with no router action.")
        return tools, llm, reply

    def test_nonobject_or_invalid_native_arguments_never_execute_hardware_defaults(self):
        for arguments in ("", "{", "null", "[]", "true", "42", '"text"', None, [], False, 4):
            with self.subTest(arguments=arguments):
                tools, llm, reply = self._run(native(arguments))
                self.assertEqual(tools.executed, [])
                self.assertEqual(reply.trace[0]["result"]["executed"], False)
                self.assertIsNone(reply.trace[0]["args"])
                self.assertIn("error", reply.trace[0]["result"])
                self.assertEqual(llm.received[-1][-1]["role"], "tool")

    def test_missing_arguments_are_different_from_explicit_empty_object(self):
        message = native({})
        del message["tool_calls"][0]["function"]["arguments"]
        tools, _, reply = self._run(message)
        self.assertEqual(tools.executed, [])
        self.assertEqual(reply.trace[0]["result"]["error"]["code"], "missing_arguments")
        tools, _, _ = self._run(native("{}"))
        self.assertEqual(tools.executed, [("check_hardware", {})])

    def test_duplicate_keys_nonfinite_and_oversized_arguments_are_rejected(self):
        for arguments in ('{"log_text":"first","log_text":"second"}', '{"x":NaN}',
                          {"x": math.inf}, {"log_text": "x" * (MAX_TOOL_ARGUMENT_CHARS + 1)}):
            tools, _, reply = self._run(native(arguments, "read_logs"))
            self.assertEqual(tools.executed, [])
            self.assertIn(reply.trace[0]["result"]["error"]["code"],
                          {"invalid_argument_json", "arguments_too_large"})

    def test_rejected_arguments_are_not_echoed_to_trace_or_error(self):
        tools, llm, reply = self._run(native('{"log_text":"PRIVATE_MARKER"'))
        self.assertNotIn("PRIVATE_MARKER", json.dumps(reply.trace))
        self.assertNotIn("PRIVATE_MARKER", json.dumps(llm.received[-1]))
        self.assertFalse(tools.executed)

    def test_unknown_or_malformed_names_never_reach_dispatch(self):
        for name in ("run_shell", "../../tool", None, ["check_hardware"], "x" * 100):
            tools, _, reply = self._run(native("{}", name))
            self.assertFalse(tools.executed)
            self.assertFalse(reply.trace[0]["result"]["executed"])

    def test_invalid_native_envelopes_are_structured_rejections(self):
        cases = [None, [], "not-a-message", {"tool_calls": {}}, {"tool_calls": [None]},
                 {"tool_calls": [{"function": None}]}, {"tool_calls": [{"type": "custom", "function": {}}]},
                 {"content": {"unsafe": "not text"}}]
        for message in cases:
            tools, _, reply = self._run(message)
            self.assertFalse(tools.executed)
            self.assertIn("error", reply.trace[0]["result"])

    def test_entire_oversized_batch_is_rejected_instead_of_running_prefix(self):
        message = native("{}")
        message["tool_calls"] *= MAX_CALLS_PER_REPLY + 1
        tools, _, reply = self._run(message)
        self.assertFalse(tools.executed)
        self.assertEqual(len(reply.trace), 1)
        self.assertEqual(reply.trace[0]["result"]["error"]["code"], "too_many_tool_calls")

    def test_inline_nonobject_missing_ambiguous_or_invalid_args_never_execute(self):
        payloads = ['[]', 'null', '{"name":"check_hardware"}',
                    '{"name":"check_hardware","arguments":null}',
                    '{"name":"check_hardware","arguments":[],"parameters":{}}',
                    '{"name":"check_hardware","tool":"read_logs","arguments":{}}',
                    '{"name":"check_hardware","arguments":false}',
                    '{"name":"check_hardware","arguments":']
        for payload in payloads:
            tools, _, reply = self._run({"content": "<tool_call>" + payload + "</tool_call>"})
            self.assertFalse(tools.executed)
            self.assertIn("error", reply.trace[0]["result"])

    def test_unclosed_inline_tag_is_rejected(self):
        tools, _, reply = self._run({"content": '<tool_call>{"name":"check_hardware","arguments":{}}'})
        self.assertFalse(tools.executed)
        self.assertEqual(reply.trace[0]["result"]["error"]["code"], "incomplete_inline_call")

    def test_valid_native_and_inline_calls_still_work(self):
        messages = [native({}), {"content": '<tool_call>{"name":"read_logs","arguments":{"log_text":"safe error"}}</tool_call>'},
                    {"content": '```json\n{"name":"read_logs","parameters":{"log_text":"safe error"}}\n```'}]
        for message in messages:
            tools, _, reply = self._run(message)
            self.assertEqual(len(tools.executed), 1)
            self.assertEqual(reply.trace[0]["chosen_by"], "llm")
            self.assertEqual(reply.trace[0]["result"], {"observed": True})

    def test_json_examples_without_tool_identifiers_are_not_executed(self):
        self.assertEqual(_tool_calls({"content": '```json\n{"a":1}\n```'}, {"check_hardware"}), [])

    def test_correlated_call_ids_are_unique_even_if_model_reuses_an_id(self):
        message = native({})
        message["tool_calls"] *= 2
        calls = _tool_calls(message, {"check_hardware"})
        self.assertEqual(len(calls), 2)
        self.assertEqual(len({call["id"] for call in calls}), 2)


if __name__ == "__main__":
    unittest.main()
