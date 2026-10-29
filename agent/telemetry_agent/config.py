"""Settings for the agent, tools, and collector.

Everything can be overridden with environment variables so each teammate can
point the agent at their own runtime (Ollama or llama.cpp's llama-server).
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILL_DIR = ROOT / "skill"


def _env_path(name: str, default: Path) -> Path:
    return Path(os.environ[name]).expanduser() if name in os.environ else default


@dataclass
class Settings:
    # OpenAI-compatible endpoint. Ollama: http://localhost:11434/v1
    # llama.cpp:  http://localhost:8080/v1  (start llama-server with --jinja for tool calls)
    base_url: str = os.environ.get("AGENT_BASE_URL", "http://localhost:11434/v1")
    runtime: str = os.environ.get("AGENT_RUNTIME", "ollama")  # "ollama" or "llama.cpp"
    agent_model: str = os.environ.get("AGENT_MODEL", "qwen2.5:3b")
    models_dir: Path = field(default_factory=lambda: _env_path("MODELS_DIR", ROOT / "models"))
    results_dir: Path = field(default_factory=lambda: _env_path("RESULTS_DIR", ROOT / "results"))
    disk_budget_gb: float = float(os.environ.get("DISK_BUDGET_GB", "10"))
    max_steps: int = 6            # tool-call rounds per user message
    tool_result_chars: int = 4000  # truncate tool output before it goes back to the LLM
    guardrails: bool = True
    router: bool = True            # run the obvious tool before the LLM answers (see router.py)


def load_allow_list() -> list[dict]:
    """Models the agent is allowed to recommend or benchmark."""
    return json.loads((SKILL_DIR / "models.json").read_text())["models"]


def load_error_catalog() -> list[dict]:
    return json.loads((SKILL_DIR / "error_catalog.json").read_text())["errors"]
