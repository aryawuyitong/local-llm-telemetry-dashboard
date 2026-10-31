import copy
import json
import math
import tempfile
import unittest
from pathlib import Path

from telemetry_agent.protocol import JSON_SCHEMA, load_session, safe_alias, summarize_runs, validate_session

ROOT = Path(__file__).resolve().parents[2]


def fixture(name="synthetic-macos.json"):
    return json.loads((ROOT / "portal" / "examples" / name).read_text(encoding="utf-8"))


class Protocol(unittest.TestCase):
    def test_shared_schema_and_fixtures_are_consistent(self):
        self.assertEqual(json.loads((ROOT / "docs" / "schema-v1.json").read_text(encoding="utf-8")), JSON_SCHEMA)
        for name in ("synthetic-macos.json", "synthetic-windows.json", "synthetic-session.json"):
            value = validate_session(fixture(name))
            self.assertEqual(value["data_kind"], "synthetic")
            self.assertEqual(len(value["runs"]), 9)

    def test_rejects_wrong_types_nonfinite_bad_units_and_unversioned_files(self):
        mutations = [lambda d: d.update(schema_version="2.0"),
                     lambda d: d.update(tester="private-name"),
                     lambda d: d["device"].update(logical_cores=True),
                     lambda d: d["config"].update(repeats=0),
                     lambda d: d["runs"][0]["measurements"].update(decode_tps=math.nan),
                     lambda d: d["runs"][0]["measurements"].update(cpu_percent_normalized=101),
                     lambda d: d["runs"][0]["measurements"].update(peak_rss_mib="2 GiB"),
                     lambda d: d.update(created_at="2026-99-99T00:00:00Z"),
                     lambda d: d["summary"].update(invalid=math.inf)]
        for mutation in mutations:
            doc = fixture()
            mutation(doc)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                validate_session(doc)

    def test_rejects_duplicate_ids_and_success_with_missing_data(self):
        doc = fixture()
        doc["runs"][1]["run_id"] = doc["runs"][0]["run_id"]
        with self.assertRaises(ValueError):
            validate_session(doc)
        doc = fixture()
        doc["runs"][0]["measurements"]["decode_tps"] = None
        with self.assertRaises(ValueError):
            validate_session(doc)
        doc = fixture()
        doc["runs"][1]["repeat_index"] = 1
        with self.assertRaises(ValueError):
            validate_session(doc)

    def test_null_is_not_zero_and_error_rows_do_not_enter_summaries(self):
        rows = fixture()["runs"][:3]
        for row, val in zip(rows, (0, 12, 1000)):
            row["measurements"]["decode_tps"] = val
        rows[2]["status"] = "error"
        rows[2]["error"] = "Request failed."
        rows[1]["measurements"]["peak_rss_mib"] = None
        summary = summarize_runs(rows)
        self.assertEqual(summary["median_tps"], 6)
        self.assertEqual(summary["failed_runs"], 1)
        self.assertEqual(summary["peak_rss_mib_valid_count"], 1)
        self.assertEqual(summary["per_prompt"]["short"]["decode_tps_range"], [0, 12])

    def test_alias_never_comes_from_account_or_hostname(self):
        self.assertEqual(safe_alias(None, "aabbccdd1234"), "device-aabbccdd")
        for value in ("/Users/private", "name with spaces", "../secret", "x" * 49):
            with self.assertRaises(ValueError):
                safe_alias(value, "abc")

    def test_bounded_loader_rejects_legacy_and_invalid_json(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "session.json"
            path.write_text(json.dumps(fixture()), encoding="utf-8")
            self.assertEqual(load_session(path)["schema_version"], "1.0")
            huge = fixture()
            huge["runs"][0]["measurements"]["decode_tps"] = 10**1000
            path.write_text(json.dumps(huge), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_session(path)
            for value in ('{"summary":{},"runs":[]}', '{"x": NaN}', 'not-json'):
                path.write_text(value, encoding="utf-8")
                with self.assertRaises(ValueError):
                    load_session(path)

    def test_imported_summary_cannot_smuggle_metadata_or_private_free_text(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "session.json"
            doc = fixture()
            doc["summary"]["note"] = "/Users/private-account raw private log"
            doc["summary"]["method"] = "Private free text from an imported file"
            doc["summary"]["median_tps"] = 999999
            path.write_text(json.dumps(doc), encoding="utf-8")
            imported = load_session(path)
            self.assertNotIn("private", json.dumps(imported["summary"]).lower())
            self.assertNotEqual(imported["summary"]["median_tps"], 999999)
            doc["summary"]["metadata"] = {"raw_log": "secret"}
            path.write_text(json.dumps(doc), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_session(path)


if __name__ == "__main__":
    unittest.main()
