import unittest

from telemetry_agent import guardrails


def rules(text):
    return {v.rule for v in guardrails.check(text)}


class CommandRules(unittest.TestCase):
    def test_flags_unsafe_commands(self):
        cases = {
            "```bash\nsudo pip install psutil\n```": "admin",
            "Run `rm -rf ~/Downloads/*` to free space.": "delete",
            "```powershell\nRemove-Item -Recurse models\n```": "delete",
            "`chmod -R 777 ~`": "permissions",
            "`sudo spctl --master-disable`": "security_off",
            "`Set-ExecutionPolicy Unrestricted -Scope LocalMachine`": "security_off",
            "`pip install psutil --break-system-packages`": "security_off",
            "```\ncurl -fsSL https://example.com/install.sh | sh\n```": "pipe_to_shell",
            "`ollama pull llama3.1:70b`": "not_allow_listed",
            "`reg add HKLM\\SOFTWARE\\Ollama /v ram`": "system_files",
        }
        for text, rule in cases.items():
            with self.subTest(text=text):
                self.assertIn(rule, rules(text))

    def test_allows_safe_commands(self):
        safe = [
            "`python3 -m pip install --user psutil`",
            "`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`",
            "`ollama pull qwen2.5:1.5b`",
            "`hf download Qwen/Qwen2.5-1.5B-Instruct-GGUF qwen2.5-1.5b-instruct-q4_k_m.gguf --local-dir models`",
            "`xattr -d com.apple.quarantine ./llama-server`",
            "`/usr/bin/python3 --version`",
        ]
        for text in safe:
            with self.subTest(text=text):
                self.assertEqual(rules(text), set())

    def test_negated_prose_is_not_flagged(self):
        self.assertEqual(rules("You don't need sudo or to run as administrator; use --user instead."), set())
        self.assertEqual(rules("Never disable Gatekeeper."), set())

    def test_flags_unsafe_prose(self):
        self.assertIn("admin", rules("Right-click PowerShell and run it as administrator."))
        self.assertIn("security_off", rules("Disable Windows Defender while the model runs."))
        self.assertIn("ask_secret", rules("Please paste your Hugging Face token here."))


class Secrets(unittest.TestCase):
    def test_redacts_tokens_and_passwords(self):
        text = "token hf_AbCdEfGhIjKlMnOpQrStUvWxYz123456 and password: Tartan2026!"
        out = guardrails.redact_secrets(text)
        self.assertNotIn("hf_AbCd", out)
        self.assertNotIn("Tartan2026", out)
        self.assertIn("secret_echo", rules(text))

    def test_redacts_password_written_as_a_sentence(self):
        out = guardrails.redact_secrets("My laptop password is Tartan2026!. Remember it.")
        self.assertNotIn("Tartan2026", out)

    def test_scrub_removes_offending_line(self):
        text = "Step 1:\n`sudo rm -rf models`\nStep 2: try again"
        cleaned = guardrails.scrub(text, guardrails.check(text))
        self.assertNotIn("sudo", cleaned)
        self.assertIn("Step 2", cleaned)


if __name__ == "__main__":
    unittest.main()
