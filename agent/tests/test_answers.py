"""The questions a new student really asks are answered from real checks, not by a small model."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from telemetry_agent import actions, answers, guardrails, helper
from telemetry_agent.config import Settings

HARDWARE = {"os": "macOS", "os_version": "27.0.1", "arch": "arm64", "cpu_model": "Apple M5", "cpu_cores_physical": 10,
            "cpu_cores_logical": 10, "total_ram_gb": 16.0, "available_ram_gb": 5.4, "free_disk_gb": 42.5,
            "gpu": "Apple GPU (Metal, shares system RAM)", "python": "3.13.1", "running_as_admin": False}
RUNNING = {"name": "Ollama", "installed": True, "running": True, "models": ["qwen2.5:0.5b", "qwen2.5:3b"],
           "broken_models": ["qwen2.5:1.5b"], "lab_models": ["qwen2.5:0.5b", "qwen2.5:3b"],
           "download_url": actions.OLLAMA_DOWNLOAD, "models_dir": "/Users/x/.ollama/models", "models_dir_exists": True}
STOPPED = {**RUNNING, "running": False, "models": [], "broken_models": [], "lab_models": []}
NOTHING = {**STOPPED, "installed": False}
EMPTY = {**RUNNING, "models": [], "broken_models": [], "lab_models": []}


class Base(unittest.TestCase):
    runtime = RUNNING

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.lab = helper.Lab(Settings(base_url="http://127.0.0.1:9/v1", results_dir=Path(tmp.name)))
        for target, value in ((self.lab, ("runtime_state", self.runtime)), (self.lab.tools, ("check_hardware", HARDWARE))):
            patcher = mock.patch.object(target, value[0], return_value=value[1])
            patcher.start()
            self.addCleanup(patcher.stop)

    def ask(self, text):
        return answers.answer(self.lab, text)


class WhatTheStudentAsked(Base):
    def test_the_four_questions_that_failed_on_nov_6(self):
        reopen = self.ask("I closed my laptop yesterday. How do I open this again and use my model?")
        self.assertEqual(reopen["id"], "reopen")
        self.assertIn("Start Lab Helper", reopen["text"])
        self.assertIn("ollama run qwen2.5:0.5b", reopen["text"])
        self.assertNotIn("python3 --version", reopen["text"])

        homework = self.ask("Can I use this model for my homework at CMU?")
        self.assertEqual(homework["id"], "course_rules")
        self.assertIn("each course sets its own", homework["text"].lower())
        self.assertNotRegex(homework["text"].lower(), r"\byes\b|you can use it for your homework")

        where = self.ask("Where did the model get saved on my computer?")
        self.assertEqual(where["id"], "where_models")
        self.assertIn("/Users/x/.ollama/models", where["text"])
        self.assertIn("qwen2.5:1.5b", where["text"])  # listed, but its file is gone
        self.assertEqual(where["links"][0]["goto"], "mylab")

        working = self.ask("Is my model working right now?")
        self.assertEqual(working["id"], "status")
        self.assertIn("qwen2.5:0.5b", working["text"])
        self.assertEqual(working["proposals"], [("first_prompt", {"model": "qwen2.5:0.5b"})])

    def test_paraphrases_reach_the_same_answer(self):
        cases = {
            "status": ["hey so i finished the download thing, am i good to go", "what's next?", "is everything set up", "did it work?",
                       "does my model work", "is ollama running", "my ai isn't answering", "what do i do now", "did the download finish"],
            "reopen": ["how do i start this again tomorrow", "i restarted my mac, now what", "how do I use it from the terminal", "how do i talk to it again after i shut my computer"],
            "where_models": ["where are my models", "where's the file", "where is it stored", "how do i find the model on my computer"],
            "my_models": ["what models do i have", "which models are installed", "list my models", "how many models do I have"],
            "fit": ["which model fits my laptop?", "what can my laptop run", "what model should i download", "recommend a model", "do i have enough ram for this", "what's the fastest model i can run", "which of these models is the smartest"],
            "course_rules": ["is it cheating to use this", "am i allowed to use this on my exam", "can i use it for an assignment", "will my professor know if i use this"],
            "measurements": ["what did I measure", "show my results", "how fast is my model", "show me what you measured"],
            "changed": ["what did the lab change on my laptop", "how do i uninstall all of this", "how much space is this using", "how much room is this taking up on my mac"],
            "hardware": ["how much memory do i have", "what are my specs"],
            "privacy": ["does this send my questions to the internet", "is this private", "does it work offline", "do I need internet", "does openai see what i type", "can i use it on a plane", "is my data safe"],
            "good_for": ["what is it good for", "is it as good as chatgpt", "can it browse the web", "what should I ask it"],
            "glossary": ["what does tokens per second mean?", "what is quantization", "what's a token", "explain context", "what is ollama",
                         "what's the difference between local and cloud"],
            "slow": ["why is it so slow", "it's taking forever"],
            "last_problem": ["what went wrong", "why did that fail"],
            "what_you_do": ["what can you do", "hi", "what's this lab for"],
            "download_time": ["how long will the download take"],
            "stop_model": ["how do i stop the model"],
            "health": ["i need help", "how do i get help from my ta", "run a health check"],
        }
        for intent, questions in cases.items():
            for question in questions:
                got = self.ask(question)
                self.assertIsNotNone(got, question)
                self.assertEqual(got["id"], intent, question)

    def test_open_questions_are_left_for_the_model(self):
        for question in ["Explain how photosynthesis works", "Why might my guess have been off?", "Write me a haiku about laptops",
                         "can you help me with my homework on cells", "is it safe to turn off my firewall", "what is a class in python"]:
            self.assertIsNone(self.ask(question), question)

    def test_every_answer_passes_the_lab_s_own_command_check(self):
        for question in ["where are my models", "is my model working", "how do i open this again", "which model fits", "what models do i have",
                         "what changed", "how much memory do i have", "is this private", "what is it good for", "what is a token",
                         "tell me about qwen2.5:7b", "why is it slow", "what can you do", "can i use this for homework"]:
            got = self.ask(question)
            self.assertEqual(guardrails.check(got["text"]), [], question)

    def test_no_model_ever_named_that_is_not_real(self):
        got = self.ask("what models do i have")
        self.assertIn("qwen2.5:0.5b", got["text"])
        self.assertIn("qwen2.5:3b", got["text"])
        self.assertNotIn("any", got["text"].split())


class CardsNotCommands(Base):
    def test_asking_for_a_step_gives_its_card(self):
        self.assertEqual(self.ask("download qwen2.5:1.5b")["proposals"], [("pull_model", {"model": "qwen2.5:1.5b"})])
        self.assertEqual(self.ask("please measure qwen2.5:3b")["proposals"], [("benchmark", {"model": "qwen2.5:3b", "repeats": 3})])
        self.assertEqual(self.ask("say hello to qwen2.5:0.5b")["proposals"], [("first_prompt", {"model": "qwen2.5:0.5b"})])
        self.assertEqual(self.ask("remove qwen2.5:0.5b")["proposals"], [("remove_model", {"model": "qwen2.5:0.5b"})])

    def test_a_model_already_here_is_not_downloaded_again(self):
        got = self.ask("download qwen2.5:3b")
        self.assertEqual(got["proposals"], [])
        self.assertIn("already", got["text"])

    def test_a_model_not_here_cannot_be_measured_yet(self):
        got = self.ask("measure qwen2.5:7b")
        self.assertEqual(got["proposals"], [("pull_model", {"model": "qwen2.5:7b"})])
        self.assertIn("isn't on this laptop", got["text"])

    def test_apps(self):
        app_context = {"manager": {"installed": True}}
        with mock.patch("telemetry_agent.answers.app_path", return_value=None), \
             mock.patch("telemetry_agent.answers.app_context", return_value=app_context):
            self.assertEqual(self.ask("install vs code")["proposals"][0][1], {"app": "vscode"})
        got = self.ask("install slack")
        self.assertEqual(got["proposals"], [])
        self.assertIn("Visual Studio Code", got["text"])

    def test_cards_come_out_of_chat_ready_to_approve(self):
        reply = self.lab.chat("download qwen2.5:1.5b")
        self.assertEqual(reply["mode"], "checked")
        self.assertEqual(reply["proposals"][0]["action"], "pull_model")
        self.assertTrue(reply["proposals"][0]["why"])

    def test_checked_answers_need_no_model_and_no_lock(self):
        self.lab._operation_lock.acquire()
        try:
            reply = self.lab.chat("where are my models")
        finally:
            self.lab._operation_lock.release()
        self.assertEqual(reply["mode"], "checked")
        self.assertIsNone(reply["model"])
        self.assertIn("/Users/x/.ollama/models", reply["text"])  # the real path, not "[local path omitted]"

    def test_a_pasted_secret_never_reaches_a_canned_answer(self):
        self.assertIsNone(answers.answer(self.lab, "where are my models? my password is hunter2 and sk-abcdefghijklmnopqrstuvwxyz123456")
                          if guardrails.redact_secrets("sk-abcdefghijklmnopqrstuvwxyz123456") == "sk-abcdefghijklmnopqrstuvwxyz123456" else None)
        with mock.patch.object(answers, "answer") as canned, mock.patch.object(self.lab, "_agent_model", return_value=None):
            self.lab.chat("my token is sk-abcdefghijklmnopqrstuvwxyz123456 where are my models")
        canned.assert_not_called()

    def test_the_log_records_which_check_answered_never_the_words(self):
        self.lab.chat("where are my secret thesis models")
        logged = str(self.lab.changes())
        self.assertIn("where_models", logged)
        self.assertNotIn("thesis", logged)


class TheModelChoosesCodeWrites(Base):
    def picks(self, chosen, text, model="qwen2.5:3b"):
        with mock.patch.object(answers, "ChatClient") as client:
            client.return_value.choose_tools.return_value = chosen
            got = answers.pick(self.lab, model, text)
        return got, client

    def test_the_model_chooses_the_topic_and_code_writes_the_facts(self):
        got, _ = self.picks(["where_models"], "where did my stuff go")
        self.assertEqual(got["id"], "where_models")
        self.assertEqual(got["picked_by"], "qwen2.5:3b")
        self.assertIn("/Users/x/.ollama/models", got["text"])

    def test_none_and_nonsense_leave_it_open(self):
        self.assertIsNone(self.picks(["none"], "tell it to me again")[0])
        self.assertIsNone(self.picks([], "is it on")[0])
        self.assertIsNone(self.picks(["rm -rf"], "is it on")[0])

    def test_small_models_never_choose(self):
        for model in ("qwen2.5:0.5b", "qwen2.5:1.5b"):  # each chose correctly only 6 times in 24
            got, client = self.picks(["status"], "is it on", model=model)
            self.assertIsNone(got)
            client.assert_not_called()

    def test_common_wordings_work_with_no_chooser_at_all(self):
        cases = {"status": ["is ollama even on", "nothing is happening when I type", "how do i know it's actually running on my laptop"],
                 "changed": ["what's taking up space"], "good_for": ["why does it make stuff up"], "hardware": ["what's my free memory"],
                 "privacy": ["does it save my chats", "can my roommate read this"], "reopen": ["how do i come back to this"],
                 "course_rules": ["can i use this for my thesis"], "fit": ["which one should I pick for coding"]}
        for intent, questions in cases.items():
            for question in questions:
                self.assertEqual(self.ask(question)["id"], intent, question)

    def test_general_questions_never_reach_the_chooser(self):
        for text in ["Explain how photosynthesis works", "Write me a haiku about laptops", "how do i reverse a string in python",
                     "What is the capital of France?", "Give me three ideas for a study break", "Summarize my essay about it"]:
            got, client = self.picks(["where_models"], text)
            self.assertIsNone(got, text)
            client.assert_not_called()

    def test_a_chooser_failure_leaves_it_open(self):
        with mock.patch.object(answers, "ChatClient") as client:
            client.return_value.choose_tools.side_effect = answers.LLMError("down")
            self.assertIsNone(answers.pick(self.lab, "qwen2.5:3b", "is it on"))

    def test_the_page_can_skip_all_of_this_with_not_what_i_asked(self):
        class Model:
            messages = []

            def ask(self, text):
                from telemetry_agent.agent import AgentReply
                return AgentReply("Model's own words.")
        self.lab._agents["qwen2.5:3b"] = Model()
        with mock.patch.object(self.lab.tools, "ensure_model_ready", return_value={}):
            reply = self.lab.chat("where are my models", open_question=True)
        self.assertEqual((reply["mode"], reply["text"]), ("local_model", "Model's own words."))

    def test_a_chosen_answer_says_who_chose(self):
        with mock.patch.object(self.lab.tools, "ensure_model_ready", return_value={}), mock.patch.object(answers, "ChatClient") as client:
            client.return_value.choose_tools.return_value = ["my_models"]
            reply = self.lab.chat("what have i got sitting on it")
        self.assertEqual((reply["mode"], reply["picked_by"]), ("checked", "qwen2.5:3b"))


class KnownErrors(Base):
    def test_a_known_error_gets_the_catalog_fix_word_for_word(self):
        got = self.ask("Error: connection refused to the local runtime")
        self.assertEqual(got["id"], "known_error")
        self.assertEqual(got["kind"], "notes")
        self.assertIn("Ollama is running on this laptop right now", got["text"])

    def test_a_question_mentioning_error_with_no_match_is_open(self):
        self.assertIsNone(self.ask("what does a floating point error mean"))

    def test_an_unknown_error_on_this_laptop_is_not_guessed_at(self):
        got = self.ask("permission denied when i run it")
        self.assertEqual(got["id"], "unknown_error")
        self.assertIn("won't guess", got["text"])


class WhenThingsAreMissing(Base):
    runtime = NOTHING

    def test_no_ollama(self):
        got = self.ask("is it working")
        self.assertIn("isn't installed", got["text"])
        self.assertEqual(got["links"][0]["goto"], "deploy")
        self.assertIn("Install Ollama", self.ask("how do i open this again")["text"])
        self.assertIn("nothing is on this laptop yet", self.ask("what models do i have")["text"].lower())


class WhenStopped(Base):
    runtime = STOPPED

    def test_stopped_offers_the_start_card(self):
        got = self.ask("is it working")
        self.assertIn("isn't running", got["text"])
        self.assertEqual(got["proposals"], [("start_runtime", {})])
        self.assertEqual(self.ask("start ollama")["proposals"], [("start_runtime", {})])


class WhenEmpty(Base):
    runtime = EMPTY

    def test_running_with_no_model_says_so_and_offers_a_download(self):
        got = self.ask("am i done")
        self.assertIn("no model", got["text"].lower())
        self.assertEqual(got["proposals"][0][0], "pull_model")


if __name__ == "__main__":
    unittest.main()
