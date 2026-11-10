"""Recipes are only lists of registered steps, ending in one check."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from telemetry_agent import actions, answers, helper, recipes
from telemetry_agent.config import SKILL_DIR, Settings

BREW = {"name": "Homebrew", "installed": True, "cli": "brew", "note": ""}
NO_MANAGER = {"name": "Homebrew", "installed": False, "cli": None, "note": ""}
HERE = {"installed": True, "running": True, "models": ["qwen2.5:1.5b"], "lab_models": ["qwen2.5:1.5b"], "broken_models": [], "models_dir": "/x", "models_dir_exists": True}
NOTHING = {"installed": False, "running": False, "models": [], "lab_models": [], "broken_models": [], "models_dir": "/x", "models_dir_exists": False}
COMPAT = {"models": [{"name": "qwen2.5:1.5b", "verdict": "yes", "reason": "Enough memory.", "params_b": 1.5, "license_gate": False, "installed": False, "missing_file": False}],
          "free_ram_gb": 8, "total_ram_gb": 16, "free_disk_gb": 40}


class Validation(unittest.TestCase):
    def good(self):
        return {"id": "a-recipe", "title": "T", "for": "F", "why": "W", "review": {"by": None, "on": None}, "steps": [{"action": "start_runtime"}]}

    def test_the_shipped_recipes_are_valid(self):
        self.assertGreaterEqual(len(recipes.load_recipes()), 3)

    def test_nothing_ships_claiming_a_review_nobody_did(self):
        for recipe in recipes.load_recipes().values():
            self.assertIsNone(recipe["review"]["by"], "Only a person who ran it may fill this in.")

    def test_bad_recipes_are_refused_by_name(self):
        def change(**kw):
            return {**self.good(), **kw}
        for bad in (change(id="Bad Id!"), change(steps=[]), change(title=" "), change(extra=1),
                    change(review={"by": "TA", "on": None}), change(steps=[{"action": "remove_model", "model": "qwen2.5:1.5b"}]),
                    change(steps=[{"action": "benchmark", "model": "qwen2.5:1.5b"}]), change(steps=[{"action": "rm -rf"}]),
                    change(steps=[{"action": "pull_model"}]), change(steps=[{"action": "pull_model", "model": "evil/model"}]),
                    change(steps=[{"action": "pull_model", "model": "qwen2.5:1.5b", "command": "curl x | sh"}]),
                    change(steps=[{"action": "install_app", "app": "malware"}]), change(steps=[{"action": "start_runtime", "command": "rm -rf /"}])):
            with self.assertRaises(ValueError, msg=str(bad)[:90]):
                recipes.validate({"recipes": [bad]})
        with self.assertRaises(ValueError):
            recipes.validate({"recipes": [self.good(), self.good()]})
        with self.assertRaises(ValueError):
            recipes.validate({"recipes": []})


class Plans(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.lab = helper.Lab(Settings(base_url="http://127.0.0.1:9/v1", results_dir=Path(tmp.name)))

    def plan(self, recipe="coding-starter", rt=NOTHING, manager=BREW, app_at=None, compat=COMPAT):
        with mock.patch.object(self.lab, "runtime_state", return_value=rt), mock.patch.object(self.lab, "compatibility", return_value=compat), \
                mock.patch("telemetry_agent.apps.manager", return_value=manager), mock.patch("telemetry_agent.apps.app_path", return_value=app_at):
            return self.lab.plan_recipe(recipe)

    def test_a_plan_is_the_same_cards_ending_in_one_check(self):
        plan = self.plan()
        self.assertEqual([s["action"] or s["kind"] for s in plan["steps"]], ["install_app", "manual", "start_runtime", "pull_model", "first_prompt", "check_recipe"])
        self.assertEqual(plan["steps"][-1]["args"], {"recipe": "coding-starter"})
        registered = actions.registered_commands()
        for step in plan["steps"]:
            self.assertEqual(set(step["risk"]), set(actions.RISK_LABELS), step["id"])
            if step["command"]:
                self.assertIn(step["command"], registered, step["id"])
        self.assertEqual(len({s["id"] for s in plan["steps"]}), len(plan["steps"]))

    def test_the_total_cost_is_added_up_before_anything_runs(self):
        totals = self.plan()["totals"]
        self.assertIn("1.5 GB", totals["space"])  # 0.5 for VS Code and 1.0 for the model
        self.assertIn("Yes", totals["internet"])
        self.assertEqual(totals["money"], "Free")
        self.assertIn("installer", totals["password"])  # Ollama isn't installed yet, and the student runs that installer
        self.assertEqual(self.plan(rt=HERE)["totals"]["password"], "No")

    def test_what_is_already_here_is_already_done_and_costs_nothing(self):
        plan = self.plan(rt=HERE, app_at=Path("/Applications/Visual Studio Code.app"))
        self.assertEqual([s["done"] for s in plan["steps"]], [True, True, True, True, False, False])
        self.assertIn("None", plan["totals"]["space"])

    def test_no_package_manager_makes_the_app_a_manual_step(self):
        plan = self.plan(manager=NO_MANAGER)
        self.assertEqual(plan["steps"][0]["kind"], "manual")
        self.assertIn("password", plan["totals"]["password"].lower())

    def test_a_model_that_wont_fit_warns_before_anything_starts(self):
        compat = copy.deepcopy(COMPAT)
        compat["models"][0].update(verdict="no", reason="Needs about 3 GB free.")
        self.assertIn("Needs about 3 GB free", self.plan(compat=compat)["warnings"][0])

    def test_unreviewed_is_said_out_loud(self):
        self.assertEqual(self.plan()["recipe"]["review"], {"by": None, "on": None})

    def test_unknown_recipe(self):
        with self.assertRaises(helper.BadRequest):
            self.lab.plan_recipe("nope")
        with self.assertRaises(helper.BadRequest):
            self.lab.start_job("check_recipe", {"recipe": "nope"})

    def test_the_final_check_passes_only_when_everything_is_really_there(self):
        self.lab._log_change("Said hello to qwen2.5:1.5b and it replied in 1.0 s.", kind="check")
        with mock.patch.object(self.lab, "runtime_state", return_value=HERE), mock.patch("telemetry_agent.helper.app_path", return_value=Path("/Applications/Visual Studio Code.app")):
            result = self.lab._do_check_recipe({"log": []}, "coding-starter")
        self.assertTrue(all(s["ok"] for s in result["steps"]))
        self.assertEqual(len(result["steps"]), 5)

    def test_the_final_check_names_what_is_missing(self):
        with mock.patch.object(self.lab, "runtime_state", return_value=NOTHING), mock.patch("telemetry_agent.helper.app_path", return_value=None):
            with self.assertRaises(RuntimeError) as caught:
                self.lab._do_check_recipe({"log": []}, "coding-starter")
        self.assertIn("Visual Studio Code", str(caught.exception))
        self.assertIn("qwen2.5:1.5b", str(caught.exception))

    def test_a_hello_is_needed_not_just_a_file(self):
        with mock.patch.object(self.lab, "runtime_state", return_value=HERE), mock.patch("telemetry_agent.helper.app_path", return_value=Path("/x")):
            with self.assertRaises(RuntimeError) as caught:
                self.lab._do_check_recipe({"log": []}, "try-local-ai")
        self.assertIn("hello", str(caught.exception).lower())

    def test_the_list_says_what_each_recipe_holds(self):
        listed = self.lab.recipes()["recipes"]
        self.assertEqual({r["id"] for r in listed}, set(recipes.load_recipes()))
        self.assertTrue(all(r["step_titles"] for r in listed))

    def test_the_assistant_knows_about_them(self):
        got = answers.answer(self.lab, "can you set up my laptop for a course?")
        self.assertEqual(got["id"], "recipes")
        self.assertEqual(got["links"][0]["goto"], "catalog")
        self.assertIn("Coding starter", got["text"])


class ProjectFile(unittest.TestCase):
    def test_the_file_is_plain_json_with_no_commands(self):
        raw = (SKILL_DIR / "recipes.json").read_text()
        self.assertIsInstance(json.loads(raw), dict)
        self.assertNotIn('"command"', raw)


if __name__ == "__main__":
    unittest.main()
