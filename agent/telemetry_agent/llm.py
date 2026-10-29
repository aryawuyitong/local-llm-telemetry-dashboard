"""Minimal client for any OpenAI-compatible chat endpoint (Ollama, llama-server).

Standard library only, so learners don't need extra packages to run the agent.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Iterator


class LLMError(RuntimeError):
    pass


class ChatClient:
    def __init__(self, base_url: str, model: str, timeout: float = 180):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def _post(self, path: str, payload: dict):
        req = urllib.request.Request(
            self.base_url + path,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            return urllib.request.urlopen(req, timeout=self.timeout)
        except urllib.error.HTTPError as e:
            raise LLMError(f"HTTP {e.code} from {path}: {e.read().decode(errors='replace')[:300]}") from e
        except urllib.error.URLError as e:
            raise LLMError(f"Could not reach {self.base_url} ({e.reason}). Is the model server running?") from e

    def chat(self, messages: list[dict], tools: list[dict] | None = None,
             temperature: float = 0.1, max_tokens: int = 700) -> dict:
        """One non-streaming call. Returns the assistant message dict."""
        payload = {"model": self.model, "messages": messages,
                   "temperature": temperature, "max_tokens": max_tokens}
        if tools:
            payload["tools"] = tools
        with self._post("/chat/completions", payload) as resp:
            body = json.loads(resp.read())
        return body["choices"][0]["message"]

    def stream(self, messages: list[dict], max_tokens: int = 128,
               temperature: float = 0.0) -> Iterator[tuple[float, str, dict | None]]:
        """Yield (timestamp, text_delta, usage_or_None) for each streamed chunk."""
        payload = {"model": self.model, "messages": messages, "stream": True,
                   "max_tokens": max_tokens, "temperature": temperature,
                   "stream_options": {"include_usage": True}}
        with self._post("/chat/completions", payload) as resp:
            for raw in resp:
                line = raw.decode(errors="replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                chunk = json.loads(data)
                choices = chunk.get("choices") or []
                delta = (choices[0].get("delta", {}).get("content") or "") if choices else ""
                yield time.perf_counter(), delta, chunk.get("usage")

    def list_models(self) -> list[str]:
        req = urllib.request.Request(self.base_url + "/models")
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return [m["id"] for m in json.loads(resp.read()).get("data", [])]
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            raise LLMError(f"Could not list models at {self.base_url}: {e}") from e
