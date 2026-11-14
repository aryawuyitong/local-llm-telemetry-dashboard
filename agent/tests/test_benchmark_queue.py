import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from telemetry_agent.config import Settings
from telemetry_agent.helper import BadRequest, Lab


class BenchmarkQueueTests(unittest.TestCase):
    SMALL, LARGE, OTHER = "qwen2.5:0.5b", "qwen2.5:1.5b", "qwen2.5:3b"

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.lab = Lab(Settings(results_dir=Path(folder.name)))
        self.installed = [self.SMALL, self.LARGE]
        self.resident = [self.SMALL]
        self.events = []

    def unload(self, tag):
        self.events.append(("unload", tag))
        self.resident.remove(tag)

    def measure(self, job, tag, repeats, guess_tps, guess_ram_gb):
        self.assertEqual(self.resident, [])
        self.events.append(("measure", tag, repeats))
        self.resident.append(tag)
        return {"runs": 9, "failed_runs": 0, "partial_runs": 0}

    def run_queue(self, unload=None, measure=None):
        with patch.object(self.lab, "runtime_state", return_value={"lab_models": self.installed}), \
             patch("telemetry_agent.helper.ChatClient") as client, \
             patch.object(self.lab, "_do_benchmark", side_effect=measure or self.measure):
            client.return_value.loaded_models.side_effect = lambda: list(self.resident)
            client.return_value.unload.side_effect = unload or self.unload
            return self.lab._do_benchmark_queue({"log": []}, self.installed, repeats=3)

    def test_switches_without_downloading_and_preserves_measurement_settings(self):
        result = self.run_queue()
        self.assertEqual(self.events, [
            ("unload", self.SMALL), ("measure", self.SMALL, 3), ("unload", self.SMALL),
            ("measure", self.LARGE, 3), ("unload", self.LARGE),
        ])
        self.assertEqual(self.resident, [])
        self.assertEqual([row["status"] for row in result["models"]], ["done", "done"])

    def test_an_unrelated_loaded_model_is_left_alone(self):
        self.resident.append(self.OTHER)
        with self.assertRaisesRegex(ValueError, "outside this selection"):
            self.run_queue()
        self.assertEqual(self.events, [])
        self.assertIn(self.OTHER, self.resident)

    def test_keeps_the_first_result_and_stops_if_memory_was_not_released(self):
        def stuck_after_measurement(tag):
            if len(self.events) == 0:
                self.unload(tag)

        result = self.run_queue(unload=stuck_after_measurement)
        self.assertEqual([row["status"] for row in result["models"]], ["done", "skipped"])
        self.assertIn("active model", result["models"][0]["error"])

    def test_rejects_duplicate_or_unapproved_tags_before_starting_a_job(self):
        for models in ([self.SMALL, self.SMALL], [self.SMALL, "some-other-tag"]):
            with self.subTest(models=models), self.assertRaises(BadRequest):
                self.lab.start_job("benchmark_queue", {"models": models})
        self.assertEqual(self.lab.jobs, {})
