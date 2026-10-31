"""Validated local-only configuration shared by the lab and runtime client."""
from __future__ import annotations

import json
import math
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parent.parent
SKILL_DIR = ROOT / "skill"


def validate_local_base_url(value: str) -> str:
    """Validate an HTTP /v1 endpoint and replace localhost with literal loopback.

    Credentials, DNS names, URL escapes, alternate IP spellings, query strings,
    fragments and arbitrary API prefixes are deliberately unsupported.
    """
    if not isinstance(value, str) or len(value) > 200 or any(ord(c) <= 32 for c in value):
        raise ValueError("Runtime URL must be a local HTTP endpoint without whitespace.")
    if any(c in value for c in ("\\", "%", "@")):
        raise ValueError("Runtime URL cannot contain credentials or URL escapes.")
    try:
        u = urlsplit(value)
        port = u.port
    except ValueError as exc:
        raise ValueError("Invalid local runtime URL.") from exc
    if (u.scheme != "http" or u.username is not None or u.password is not None
            or u.hostname not in {"localhost", "127.0.0.1", "::1"}
            or u.path.rstrip("/") != "/v1" or u.query or u.fragment
            or (port is not None and not 1 <= port <= 65535)):
        raise ValueError("Use http://127.0.0.1:PORT/v1; external endpoints are disabled.")
    host = "[::1]" if u.hostname == "::1" else "127.0.0.1"
    return urlunsplit(("http", host + (f":{port}" if port is not None else ""), "/v1", "", ""))


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.URLError("Runtime redirects are disabled.")


def local_urlopen(request, timeout=30):
    """Open a literal-loopback API request without environment proxies/redirects."""
    url = request.full_url if isinstance(request, urllib.request.Request) else str(request)
    try:
        u = urlsplit(url)
        validate_local_base_url(urlunsplit((u.scheme, u.netloc, "/v1", "", "")))
        if (u.query or u.fragment or not u.path.startswith(("/v1/", "/api/"))
                or ".." in u.path or "%" in url or "\\" in url
                or any(ord(c) <= 32 for c in url)):
            raise ValueError("Invalid runtime API path.")
        if u.hostname == "localhost":
            raise ValueError("Use the normalized literal-loopback URL before sending.")
    except ValueError as exc:
        raise urllib.error.URLError(str(exc)) from exc
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    return opener.open(request, timeout=timeout)


def _env_path(name: str, default: Path) -> Path:
    return Path(os.environ.get(name, str(default))).expanduser().resolve()


@dataclass
class Settings:
    # OpenAI-compatible endpoint. Ollama: http://localhost:11434/v1
    # llama.cpp:  http://localhost:8080/v1  (start llama-server with --jinja for tool calls)
    base_url: str = field(default_factory=lambda: os.environ.get("AGENT_BASE_URL", "http://127.0.0.1:11434/v1"))
    runtime: str = field(default_factory=lambda: os.environ.get("AGENT_RUNTIME", "ollama"))
    agent_model: str = field(default_factory=lambda: os.environ.get("AGENT_MODEL", "qwen2.5:3b"))
    models_dir: Path = field(default_factory=lambda: _env_path("MODELS_DIR", ROOT / "models"))
    results_dir: Path = field(default_factory=lambda: _env_path("RESULTS_DIR", ROOT / "results"))
    runtime_models_dir: Path = field(default_factory=lambda: _env_path("OLLAMA_MODELS", Path.home() / ".ollama" / "models"))
    runtime_install_dir: Path | None = field(default_factory=lambda: _env_path("RUNTIME_INSTALL_DIR", ROOT) if "RUNTIME_INSTALL_DIR" in os.environ else None)
    disk_budget_gb: float = field(default_factory=lambda: float(os.environ.get("DISK_BUDGET_GB", "10")))
    max_steps: int = 6            # tool-call rounds per user message
    tool_result_chars: int = 4000  # truncate tool output before it goes back to the LLM
    guardrails: bool = True
    router: bool = True            # run the obvious tool before the LLM answers (see router.py)

    def __post_init__(self):
        self.base_url = validate_local_base_url(self.base_url)
        if self.runtime not in {"ollama", "llama.cpp"}:
            raise ValueError("AGENT_RUNTIME must be ollama or llama.cpp.")
        if not isinstance(self.agent_model, str) or not self.agent_model or len(self.agent_model) > 128:
            raise ValueError("Invalid agent model identifier.")
        if (type(self.disk_budget_gb) not in (int, float) or not 0 < self.disk_budget_gb <= 10
                or not math.isfinite(self.disk_budget_gb)):
            raise ValueError("DISK_BUDGET_GB must be greater than 0 and no more than 10 GiB.")
        for name in ("models_dir", "results_dir", "runtime_models_dir"):
            setattr(self, name, Path(getattr(self, name)).expanduser().resolve())
        if self.runtime_install_dir is not None:
            self.runtime_install_dir = Path(self.runtime_install_dir).expanduser().resolve()
        if type(self.max_steps) is not int or not 1 <= self.max_steps <= 10:
            raise ValueError("max_steps must be an integer from 1 to 10.")
        if type(self.tool_result_chars) is not int or not 256 <= self.tool_result_chars <= 16000:
            raise ValueError("tool_result_chars must be between 256 and 16000.")


def load_allow_list() -> list[dict]:
    """Models the agent is allowed to recommend or benchmark."""
    return json.loads((SKILL_DIR / "models.json").read_text(encoding="utf-8"))["models"]


def load_error_catalog() -> list[dict]:
    return json.loads((SKILL_DIR / "error_catalog.json").read_text(encoding="utf-8"))["errors"]
