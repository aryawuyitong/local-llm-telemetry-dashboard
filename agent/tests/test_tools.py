import contextlib
import io
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from telemetry_agent import tools as tools_mod
from telemetry_agent.config import ROOT, Settings
from telemetry_agent.tools import Toolbox, validate_tool_args

HW = {"os": "macOS", "arch": "arm64", "cpu_model": "Test CPU", "total_ram_gb": 16,
      "available_ram_gb": 8, "free_disk_gb": 40, "running_as_admin": False}
FOOTPRINT = {"non_model_gb": 1.0, "verified": True, "basis": "test measurement", "missing": []}
INVENTORY = [{"name": "qwen2.5:0.5b", "size": 400000000, "digest": "a" * 64, "details": {}}]


class ToolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = Path(self.tmp.name)
        self.tb = Toolbox(Settings(models_dir=p / "models", results_dir=p / "results",
                                   runtime_models_dir=p / "runtime-models", base_url="http://127.0.0.1:9/v1"))
        self.hw = mock.patch.object(tools_mod, "hardware_info", return_value=dict(HW))
        self.foot = mock.patch.object(tools_mod, "installation_footprint", return_value=dict(FOOTPRINT))
        self.native = mock.patch.object(tools_mod.ChatClient, "native_get", return_value={"models": INVENTORY})
        self.hw.start(); self.foot.start(); self.native.start()
        self.addCleanup(self.hw.stop); self.addCleanup(self.foot.stop); self.addCleanup(self.native.stop)

    def test_catalog_failure_cases_match_without_model(self):
        cases = json.loads((ROOT / "evals/failures.json").read_text(encoding="utf-8"))["cases"]
        for case in cases:
            with self.subTest(case=case["id"]):
                self.assertEqual(self.tb.read_logs(case["message"])["matches"][0]["id"], case["expected"])

    def test_unknown_error_abstains(self):
        out = self.tb.read_logs("An unrecognized test failure happened")
        self.assertEqual(out["matches"], [])
        self.assertIn("exact error", out["advice"])

    def test_no_total_ram_half_fallback(self):
        with mock.patch.object(tools_mod, "hardware_info", return_value={**HW, "total_ram_gb": 64, "available_ram_gb": 1}):
            out = self.tb.recommend_model()
        self.assertEqual(out["planning_ram_gb"], 1)
        self.assertIsNone(out["recommended"])

    def test_counts_other_models_and_runtime_in_total_budget(self):
        inventory = [{"name": "unrelated-a", "size": 5 * 1024**3, "digest": "a" * 64, "details": {}},
                     {"name": "unrelated-b", "size": 5 * 1024**3, "digest": "b" * 64, "details": {}}]
        with mock.patch.object(self.tb, "_inventory", return_value=(inventory, True)):
            out = self.tb.recommend_model(available_ram_gb=64, free_disk_gb=100)
        self.assertEqual(out["budget"]["total_installed_gib"], 11)
        self.assertIsNone(out["recommended"])

    def test_predictions_and_default_three_repetitions_reach_collector(self):
        summary = {"median_tps": 20, "peak_ram_mb": 2048, "saved_to": "local-session.json"}
        with mock.patch.object(self.tb, "ensure_model_ready", return_value={"model": "qwen2.5:0.5b"}), \
             mock.patch.object(tools_mod.collector, "run_benchmark", return_value=summary.copy()) as run:
            out = self.tb.run_benchmark("qwen2.5:0.5b", guess_tps=30, guess_ram_gb=1)
        self.assertEqual(run.call_args.kwargs, {"repeats": 3, "guess_tps": 30, "guess_ram_gb": 1})
        self.assertEqual(out["prediction_check"]["tps"]["off_by_percent"], 50)
        self.assertEqual(out["prediction_check"]["ram_gb"]["actual"], 2)
        self.assertIn("saved_to", out)

    def test_concurrent_benchmark_is_rejected(self):
        entered, finish = threading.Event(), threading.Event()
        def slow(*args, **kwargs):
            entered.set()
            finish.wait(3)
            return {"median_tps": 1}
        with mock.patch.object(self.tb, "ensure_model_ready", return_value={}), \
             mock.patch.object(tools_mod.collector, "run_benchmark", side_effect=slow):
            thread = threading.Thread(target=self.tb.run_benchmark, args=("qwen2.5:0.5b",))
            thread.start()
            try:
                self.assertTrue(entered.wait(2))
                self.assertTrue(self.tb.run_benchmark("qwen2.5:0.5b")["busy"])
            finally:
                finish.set()
                thread.join(4)

    def test_valid_exact_tag_digest_and_total_budget(self):
        out = self.tb.ensure_model_ready("qwen2.5:0.5b")
        self.assertEqual(out["model_digest"], "a" * 64)
        self.assertIn("not independently verified", out["provenance"])

    def test_unknown_model_paths_and_tag_aliases_are_not_executed(self):
        for model in ("llama3.1:70b", "qwen2.5-0.5b-instruct-q4_k_m", "../models/model.gguf", "http://evil/model"):
            with self.subTest(model=model), mock.patch.object(tools_mod.collector, "run_benchmark") as run:
                self.assertIn("error", self.tb.run_benchmark(model))
                run.assert_not_called()

    def test_invalid_or_missing_digest_stops_execution(self):
        with mock.patch.object(self.tb, "_inventory", return_value=([{**INVENTORY[0], "digest": None}], True)):
            with self.assertRaisesRegex(ValueError, "digest"):
                self.tb.ensure_model_ready("qwen2.5:0.5b")

    def test_unknown_total_footprint_does_not_claim_budget_pass(self):
        with mock.patch.object(tools_mod, "installation_footprint", return_value={**FOOTPRINT, "verified": False, "missing": ["runtime"]}):
            out = self.tb.run_benchmark("qwen2.5:0.5b")
        self.assertTrue(out["supported_stop"])
        self.assertIn("unverified", out["error"])

    def test_low_live_ram_and_admin_are_stop_conditions(self):
        for patch in ({"available_ram_gb": 0.5}, {"running_as_admin": True}, {"free_disk_gb": 1}):
            with self.subTest(patch=patch), mock.patch.object(tools_mod, "hardware_info", return_value={**HW, **patch}):
                with self.assertRaises(ValueError):
                    self.tb.ensure_model_ready("qwen2.5:0.5b")

    def test_strict_argument_contract(self):
        cases = [("check_hardware", {"cmd": "whoami"}), ("check_install", {"up_to_step": True}),
                 ("run_benchmark", {"model": "qwen2.5:0.5b", "repeats": "3"}),
                 ("run_benchmark", {"model": "qwen2.5:0.5b", "guess_tps": float("nan")}),
                 ("recommend_model", {"available_ram_gb": 10**1000}),
                 ("recommend_model", {"available_ram_gb": -1}), ("read_logs", {"log_text": []}),
                 ("read_logs", {"log_text": "a" * 16001}), ("read_logs", []), ("missing", {})]
        for name, args in cases:
            with self.subTest(name=name, args=str(args)[:90]):
                self.assertIn("error", self.tb.call(name, args))

    def test_docstrings_and_schemas_are_llm_facing(self):
        schemas = self.tb.schemas()
        self.assertEqual(len(schemas), 5)
        for item in schemas:
            fn = item["function"]
            self.assertGreater(len(fn["description"]), 120)
            self.assertIs(fn["parameters"]["additionalProperties"], False)

    def test_quantization_is_not_invented_from_other_catalog_format(self):
        brief = tools_mod._brief(self.tb.allow_list[0])
        self.assertIsNone(brief["quantization"])
        self.assertFalse(brief["catalog_estimates_verified"])

    def test_cli_bench_uses_tool_gate(self):
        from telemetry_agent import __main__ as cli
        with mock.patch.object(cli.Toolbox, "run_benchmark", return_value={"error": "test stop"}) as gate, \
             contextlib.redirect_stdout(io.StringIO()):
            code = cli.main(["bench", "--model", "qwen2.5:0.5b"])
        self.assertEqual(code, 1)
        self.assertEqual(gate.call_args.kwargs["repeats"], 3)

    def test_cli_failed_benchmark_exits_nonzero_and_partial_warns(self):
        from telemetry_agent import __main__ as cli
        for failed, partial, expected in ((9, 0, 1), (1, 2, 1), (0, 9, 0)):
            stderr = io.StringIO()
            with self.subTest(failed=failed, partial=partial), \
                 mock.patch.object(cli.Toolbox, "run_benchmark", return_value={"runs": 9, "failed_runs": failed, "partial_runs": partial}), \
                 contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(stderr):
                code = cli.main(["bench", "--model", "qwen2.5:0.5b"])
            self.assertEqual(code, expected)
            self.assertTrue(stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
