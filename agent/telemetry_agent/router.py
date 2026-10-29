"""Deterministic routing: run the obvious tool before the LLM answers.

Small local models (~3B) often skip tools or call the wrong one. For the common
learner requests the right first tool is obvious, so we pick it with simple
rules and hand the result to the LLM, which only has to explain it. The LLM can
still call more tools afterwards. Turn this off (Settings.router=False) to
measure the LLM's own tool choice.
"""
from __future__ import annotations

import re

ERROR_HINT = re.compile(
    r"\berror\b|\bfailed\b|traceback|exception|not found|denied|refused|cannot|can't|couldn't|"
    r"not recognized|no such file|errno|\b[45]\d\d client|already in use|out of memory|no space left", re.I)
BENCH_HINT = re.compile(r"benchmark|test (it|how fast|the speed)|how fast|tokens per second|\btps\b|tok/s|speed", re.I)
REC_HINT = re.compile(r"\b(which|what) (model|llm)|recommend|what can my (laptop|computer|machine)|"
                      r"should i (download|use|get)|best model for", re.I)
INSTALL_HINT = re.compile(r"next step|what('?s| is) next|did i (do|install|set)|is (it|everything) (installed|set up|working)|"
                          r"check my (setup|install)|am i done", re.I)
HARDWARE_HINT = re.compile(r"my (laptop|computer|machine|hardware|specs)|how much (ram|memory|disk)", re.I)

GUESS_TPS = re.compile(r"(\d+(?:\.\d+)?)\s*(?:tokens? (?:per|a|/) ?(?:second|sec|s)|tok/s|tps)", re.I)
GUESS_RAM = re.compile(r"(\d+(?:\.\d+)?)\s*GB(?:\s+of)?\s+(?:RAM|memory)", re.I)


def route(text: str, model_names: list[str], is_known_error=None) -> list[tuple[str, dict]]:
    """Return the tool calls (name, args) to run before the LLM sees the message.

    `is_known_error(text)` lets the caller also catch errors that match the catalog
    but contain no generic error words (e.g. "bad CPU type in executable").
    """
    if ERROR_HINT.search(text) or (is_known_error and is_known_error(text)):
        return [("read_logs", {"log_text": text})]

    mentioned = next((m for m in sorted(model_names, key=len, reverse=True)
                      if re.search(rf"(?<![\w.:]){re.escape(m)}(?![\w.:])", text, re.I)), None)
    if mentioned and BENCH_HINT.search(text):
        args: dict = {"model": mentioned}
        if (g := GUESS_TPS.search(text)):
            args["guess_tps"] = float(g.group(1))
        if (g := GUESS_RAM.search(text)):
            args["guess_ram_gb"] = float(g.group(1))
        return [("run_benchmark", args)]

    if REC_HINT.search(text):
        return [("recommend_model", {})]
    if INSTALL_HINT.search(text):
        return [("check_install", {})]
    if HARDWARE_HINT.search(text):
        return [("check_hardware", {})]
    return []
