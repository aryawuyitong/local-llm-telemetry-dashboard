"""Local-only HTTP client; legacy OpenAI streaming remains available.

The collector uses Ollama's native /api/chat stream so its final eval_count and
nanosecond eval_duration are available. See https://docs.ollama.com/api/chat.
A text chunk is never treated as a token. No response text is persisted here.
"""
from __future__ import annotations

import json
import math
import re
import time
import urllib.error
import urllib.request
from typing import Iterator
from http.client import HTTPException

from .config import local_urlopen, validate_local_base_url


class LLMError(RuntimeError):
    pass


class ChatClient:
    def __init__(self, base_url: str, model: str, timeout: float = 180):
        self.base_url = validate_local_base_url(base_url)
        self.model = model
        self.timeout = timeout

    def _request(self, url: str, payload: dict | None = None, timeout: float | None = None):
        req = urllib.request.Request(url, data=json.dumps(payload, allow_nan=False).encode() if payload is not None else None,
                                     headers={"Content-Type": "application/json"} if payload is not None else {})
        try:
            return local_urlopen(req, timeout=timeout or self.timeout)
        except urllib.error.HTTPError as e:
            # Do not echo arbitrary runtime errors, which may contain prompts, paths or secrets.
            raise LLMError(f"Local runtime returned HTTP {e.code}.") from e
        except (urllib.error.URLError, TimeoutError, OSError, HTTPException) as e:
            raise LLMError("The local model server could not be reached or timed out.") from e

    def _post(self, path: str, payload: dict):
        return self._request(self.base_url + path, payload)

    def _native_url(self, path: str) -> str:
        if path not in ("/api/chat", "/api/tags", "/api/ps", "/api/version", "/api/show"):
            raise ValueError("Unsupported native API path")
        return self.base_url[:-3] + path

    def native_get(self, path: str) -> dict:
        try:
            with self._request(self._native_url(path), timeout=5) as resp:
                body = json.loads(resp.read(1024 * 1024))
            if not isinstance(body, dict):
                raise ValueError("not an object")
            return body
        except (ValueError, UnicodeError) as e:
            raise LLMError("The local runtime returned invalid metadata.") from e
        except (OSError, TimeoutError, HTTPException) as e:
            raise LLMError("The local metadata response was interrupted or timed out.") from e

    def chat(self, messages: list[dict], tools: list[dict] | None = None,
             temperature: float = 0.1, max_tokens: int = 700) -> dict:
        """One compatible non-streaming call. Returns an assistant message dict."""
        payload = {"model": self.model, "messages": messages,
                   "temperature": temperature, "max_tokens": max_tokens}
        if tools:
            payload["tools"] = tools
        try:
            with self._post("/chat/completions", payload) as resp:
                body = json.loads(resp.read(2 * 1024 * 1024))
            message = body["choices"][0]["message"]
            if not isinstance(message, dict):
                raise ValueError("not a message")
            return message
        except (KeyError, IndexError, ValueError, UnicodeError, TypeError) as e:
            raise LLMError("The local runtime returned an invalid chat response.") from e
        except (OSError, TimeoutError, HTTPException) as e:
            raise LLMError("The local chat response was interrupted or timed out.") from e

    def stream(self, messages: list[dict], max_tokens: int = 128,
               temperature: float = 0.0) -> Iterator[tuple[float, str, dict | None]]:
        """Legacy SSE interface: yield (monotonic timestamp, text, usage-or-None)."""
        payload = {"model": self.model, "messages": messages, "stream": True,
                   "max_tokens": max_tokens, "temperature": temperature,
                   "stream_options": {"include_usage": True}}
        try:
            with self._post("/chat/completions", payload) as resp:
                while True:
                    raw = resp.readline(1024 * 1024 + 1)
                    if not raw:
                        break
                    if len(raw) > 1024 * 1024:
                        raise LLMError("Local runtime stream frame is too large.")
                    line = raw.decode().strip()
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    chunk = json.loads(data)
                    choices = chunk.get("choices") or []
                    delta = (choices[0].get("delta", {}).get("content") or "") if choices else ""
                    if not isinstance(delta, str):
                        raise ValueError("invalid content")
                    yield time.perf_counter(), delta, chunk.get("usage")
        except (ValueError, UnicodeError, TypeError, AttributeError, IndexError) as e:
            raise LLMError("The local runtime returned an invalid stream.") from e
        except (OSError, TimeoutError, HTTPException) as e:
            raise LLMError("The local runtime stream was interrupted or timed out.") from e

    def benchmark_stream(self, messages: list[dict], runtime: str = "ollama", max_tokens: int = 128,
                         temperature: float = 0.0, context_tokens: int = 2048):
        """Same tuple shape as stream; Ollama usage includes native decode timings.

        For other runtimes we retain their compatible stream usage. The collector
        reports TPS unavailable unless a valid decode token count AND duration are
        supplied; completion_tokens alone is insufficient for native decode TPS.
        """
        if runtime != "ollama":
            yield from self.stream(messages, max_tokens=max_tokens, temperature=temperature)
            return
        payload = {"model": self.model, "messages": messages, "stream": True,
                   "options": {"temperature": temperature, "num_predict": max_tokens, "num_ctx": context_tokens},
                   "keep_alive": "5m"}
        done = False
        try:
            with self._request(self._native_url("/api/chat"), payload) as resp:
                while True:
                    raw = resp.readline(1024 * 1024 + 1)
                    if not raw:
                        break
                    if len(raw) > 1024 * 1024:
                        raise LLMError("Local runtime stream frame is too large.")
                    if not raw.strip():
                        continue
                    chunk = json.loads(raw)
                    if chunk.get("error"):
                        raise LLMError("The local runtime reported an inference error.")
                    delta = (chunk.get("message") or {}).get("content") or ""
                    if not isinstance(delta, str):
                        raise ValueError("invalid content")
                    usage = None
                    if chunk.get("done") is True:
                        done = True
                        usage = {key: chunk.get(key) for key in (
                            "eval_count", "eval_duration", "prompt_eval_count", "prompt_eval_duration", "load_duration")}
                        usage["source"] = "ollama_native"
                        # Keep compatibility with consumers of the old usage shape.
                        usage["completion_tokens"] = chunk.get("eval_count")
                    yield time.perf_counter(), delta, usage
                    if done:
                        break
            if not done:
                raise LLMError("The local runtime ended its stream without a completion record.")
        except (ValueError, UnicodeError, TypeError, AttributeError) as e:
            raise LLMError("The local runtime returned an invalid benchmark stream.") from e
        except (OSError, TimeoutError, HTTPException) as e:
            raise LLMError("The local runtime stream was interrupted or timed out.") from e

    def metadata(self, runtime: str = "ollama") -> dict:
        """Best-effort version/digest/config facts, without copying paths or host IDs."""
        result = {"runtime_version": None, "model_digest": None, "quantization": None,
                  "acceleration": "unknown", "other_models_resident": False, "context_tokens": None}
        if runtime != "ollama":
            return result
        for path in ("/api/version", "/api/tags", "/api/ps"):
            try:
                body = self.native_get(path)
            except LLMError:
                continue
            if path == "/api/version":
                version = body.get("version")
                if isinstance(version, str) and re.fullmatch(r"[A-Za-z0-9._+-]{1,80}", version):
                    result["runtime_version"] = version
                continue
            models = body.get("models", [])
            if not isinstance(models, list):
                continue
            for item in models:
                if not isinstance(item, dict):
                    continue
                name = item.get("name") or item.get("model")
                matches = name in (self.model, self.model + ":latest")
                if not matches:
                    if path == "/api/ps":
                        result["other_models_resident"] = True
                    continue
                for field, target in (("digest", "model_digest"),):
                    val = item.get(field)
                    if isinstance(val, str) and re.fullmatch(r"(?:sha256:)?[a-fA-F0-9]{64}", val):
                        result[target] = val
                details = item.get("details") or {}
                quant = details.get("quantization_level") if isinstance(details, dict) else None
                if isinstance(quant, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,40}", quant):
                    result["quantization"] = quant
                if path == "/api/ps":
                    vram = item.get("size_vram")
                    if (type(vram) in (int, float) and 0 <= vram <= 2**60 and math.isfinite(vram)):
                        result["acceleration"] = "gpu-assisted" if vram > 0 else "cpu"
                    context = item.get("context_length")
                    if isinstance(context, int) and not isinstance(context, bool) and context > 0:
                        result["context_tokens"] = context
        return result

    def list_models(self) -> list[str]:
        try:
            with self._request(self.base_url + "/models", timeout=5) as resp:
                body = json.loads(resp.read(1024 * 1024))
            return [m["id"] for m in body.get("data", []) if isinstance(m, dict) and isinstance(m.get("id"), str)]
        except (ValueError, UnicodeError, TypeError, AttributeError) as e:
            raise LLMError("The local runtime returned an invalid model list.") from e
        except (OSError, TimeoutError, HTTPException) as e:
            raise LLMError("The local model list response was interrupted or timed out.") from e
