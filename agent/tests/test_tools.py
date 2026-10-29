import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from telemetry_agent import tools as tools_mod
from telemetry_agent.config import ROOT, Settings
from telemetry_agent.tools import Toolbox


def toolbox(tmp: Path) -> Toolbox:
    return Toolbox(Settings(models_dir=tmp / "models", results_dir=tmp / "results",
                            base_url="http://127.0.0.1:9/v1"))  # port 9: nothing listens


class ReadLogs(unittest.TestCase):
    def test_every_scripted_failure_matches_its_catalog_entry(self):
        cases = json.loads((ROOT / "evals" / "failures.json").read_text())["cases"]
        tb = Toolbox(Settings())
        for c in cases:
            with self.subTest(case=c["id"]):
                top = tb.read_logs(c["message"])["matches"][0]["id"]
                self.assertEqual(top, c["expected"])

    def test_unknown_error_asks_for_details(self):
        out = Toolbox(Settings()).read_logs("something weird happened")
        self.assertEqual(out["matches"], [])
        self.assertIn("exact error", out["advice"])

    def test_catalog_fixes_pass_the_guardrails(self):
        from telemetry_agent import guardrails
        for e in Toolbox(Settings()).catalog:
            for step in e["fix"]:
                with self.subTest(entry=e["id"], step=step):
                    self.assertEqual(guardrails.check(step), [])


class RecommendModel(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.tb = toolbox(self.tmp)

    def test_small_laptop_gets_small_model(self):
        out = self.tb.recommend_model(available_ram_gb=4, free_disk_gb=50)
        self.assertLessEqual(out["recommended"]["needs_free_ram_gb"], 3.0)
        self.assertFalse(out["recommended"]["requires_license_acceptance"])

    def test_big_laptop_gets_bigger_model_within_budget(self):
        out = self.tb.recommend_model(available_ram_gb=12, free_disk_gb=50)
        self.assertGreaterEqual(out["recommended"]["params_billion"], 3)
        self.assertLessEqual(out["recommended"]["download_file_size_gb"], 10)

    def test_no_space_means_no_recommendation(self):
        out = self.tb.recommend_model(available_ram_gb=1, free_disk_gb=1)
        self.assertIsNone(out["recommended"])
        self.assertIn("Close other apps", out["explanation"])


class OtherTools(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.tb = toolbox(self.tmp)

    def test_check_hardware_has_the_basics(self):
        hw = self.tb.check_hardware()
        for key in ("os", "arch", "total_ram_gb", "available_ram_gb", "free_disk_gb", "running_as_admin"):
            self.assertIn(key, hw)

    def test_check_install_stops_at_first_failing_step(self):
        with mock.patch.object(tools_mod.shutil, "which", return_value="/usr/local/bin/ollama"):
            out = self.tb.check_install()
        self.assertEqual(out["next_step"], "server")      # nothing listens on port 9
        self.assertIn("fix", out["steps"][-1])

    def test_benchmark_refuses_models_off_the_allow_list(self):
        self.assertIn("not on the allow-list", self.tb.run_benchmark("llama3.1:70b")["error"])

    def test_guess_comparison(self):
        out = tools_mod._compare_guess({"median_tps": 20.0, "peak_ram_mb": 2048}, guess_tps=30, guess_ram_gb=1)
        self.assertEqual(out["tps"]["off_by_percent"], 50)
        self.assertEqual(out["ram_gb"]["actual"], 2.0)

    def test_schemas_have_docstrings_for_the_llm(self):
        schemas = self.tb.schemas()
        self.assertEqual(len(schemas), 5)
        for s in schemas:
            self.assertGreater(len(s["function"]["description"]), 100)


if __name__ == "__main__":
    unittest.main()
