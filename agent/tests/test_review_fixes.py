"""Fixes from the review of the one-download pull request: the shared changes log, graphics names and how to start again."""
import json
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

from telemetry_agent import helper, system
from telemetry_agent.config import ROOT, Settings

AGENT = Path(__file__).resolve().parents[1]


class ChangesLog(unittest.TestCase):
    def test_two_helper_processes_never_lose_each_others_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = textwrap.dedent(f"""
                import sys
                from pathlib import Path
                from telemetry_agent import helper
                from telemetry_agent.config import Settings
                lab = helper.Lab(Settings(base_url="http://127.0.0.1:9/v1", results_dir=Path({tmp!r})))
                for i in range(40):
                    lab._log_change(f"{{sys.argv[1]}} {{i}}", kind="check")
            """)
            runs = [subprocess.Popen([sys.executable, "-c", script, name], cwd=AGENT) for name in ("first", "second")]
            self.assertEqual([p.wait(timeout=60) for p in runs], [0, 0])
            items = json.loads((Path(tmp) / "changes" / "log.json").read_text(encoding="utf-8"))
            self.assertEqual(len(items), 80)  # every entry from both processes survived
            self.assertEqual({i["what"].split()[0] for i in items}, {"first", "second"})

    def test_undo_marks_the_log_as_it_is_now_not_an_old_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            lab = helper.Lab(Settings(base_url="http://127.0.0.1:9/v1", results_dir=Path(tmp)))
            lab._log_change("Downloaded m", undo_model="qwen2.5:0.5b")
            lab._log_change("Something logged in the meantime", kind="check")
            lab._mark_undone("undo_model", "qwen2.5:0.5b", "Removed qwen2.5:0.5b (undo).")
            items = lab.changes()["changes"]
            self.assertEqual([i["what"] for i in items], ["Downloaded m", "Something logged in the meantime", "Removed qwen2.5:0.5b (undo)."])
            self.assertTrue(items[0]["undone"])


class StartAgain(unittest.TestCase):
    def test_each_system_is_told_the_start_file_the_start_guide_uses(self):
        for system_name, launcher, words in (("Darwin", "Start Lab on Mac.command", "drag"), ("Windows", "windows_set_up.py", "PowerShell")):
            with mock.patch("telemetry_agent.helper.platform.system", return_value=system_name):
                name, how = helper.start_again()
            self.assertEqual(name, launcher)
            self.assertIn(words, how)
            self.assertTrue((ROOT.parent / launcher).is_file(), launcher)  # it's really at the top of the folder
            self.assertNotIn("Start Lab Helper", how)


class Graphics(unittest.TestCase):
    def windows(self, stdout="", returncode=0, error=None):
        run = mock.Mock(side_effect=error) if error else mock.Mock(return_value=subprocess.CompletedProcess([], returncode, stdout, ""))
        return mock.patch.multiple("telemetry_agent.system", shutil=mock.Mock(which=mock.Mock(return_value=None)),
                                   platform=mock.Mock(system=mock.Mock(return_value="Windows")),
                                   subprocess=mock.Mock(run=run, SubprocessError=subprocess.SubprocessError, CompletedProcess=subprocess.CompletedProcess))

    def test_a_separate_card_wins_over_built_in_graphics_of_the_same_brand(self):
        with self.windows("AMD Radeon(TM) Graphics\nAMD Radeon RX 7600S\n"):
            self.assertEqual(system.gpu_name(), "AMD Radeon RX 7600S")
        with self.windows("Intel(R) Arc(TM) Graphics\nNVIDIA GeForce RTX 4060 Laptop GPU\n"):
            self.assertEqual(system.gpu_name(), "NVIDIA GeForce RTX 4060 Laptop GPU")
        with self.windows("Intel(R) Arc(TM) A770 Graphics\n"):
            self.assertEqual(system.gpu_name(), "Intel(R) Arc(TM) A770 Graphics")

    def test_built_in_graphics_alone_is_still_named(self):
        with self.windows("AMD Radeon(TM) Graphics\nMicrosoft Basic Display Adapter\n"):
            self.assertEqual(system.gpu_name(), "AMD Radeon(TM) Graphics")

    def test_a_failed_lookup_is_not_reported_as_no_graphics(self):
        for kwargs in ({"returncode": 1}, {"error": subprocess.TimeoutExpired("powershell", 8)}, {"error": UnicodeDecodeError("utf-8", b"\xff", 0, 1, "bad")}):
            with self.windows(**kwargs):
                self.assertEqual(system.gpu_name(), system.GPU_UNCHECKED, kwargs)
        with self.windows(""):  # Windows answered, and listed nothing
            self.assertIsNone(system.gpu_name())

    def test_odd_characters_are_decoded_safely(self):
        with self.windows():
            system.gpu_name()
            kwargs = system.subprocess.run.call_args.kwargs
        self.assertEqual((kwargs["encoding"], kwargs["errors"]), ("utf-8", "replace"))


class Launchers(unittest.TestCase):
    def test_setup_keeps_no_pip_cache_and_waits_for_another_window(self):
        for name in ("../windows_set_up.py", "Start Lab Helper.command"):
            text = (AGENT / name).read_text(encoding="utf-8")
            self.assertIn("--no-cache-dir", text, name)
            self.assertIn(".setup-lock", text, name)
        # No .bat launcher at the top or in agent/ (a .venv's own activate.bat doesn't count).
        self.assertFalse(list(ROOT.parent.glob("*.bat")) + list(AGENT.glob("*.bat")), "Windows starts only with python windows_set_up.py")


if __name__ == "__main__":
    unittest.main()
