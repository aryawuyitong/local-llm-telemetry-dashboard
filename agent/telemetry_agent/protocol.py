"""Versioned, anonymous interchange format shared by the collector and portal.

Only identifiers and measurements are exported: no user names, host names,
endpoint URLs, filesystem paths, input text, generated text, or raw logs.
Validation uses the small JSON-Schema subset below, without another dependency.
"""
from __future__ import annotations

import json
import math
import re
import statistics
from datetime import datetime
from pathlib import Path

SCHEMA_VERSION = "1.0"
PROTOCOL_VERSION = "local-llm-lab/1"
MAX_SESSION_BYTES = 5 * 1024 * 1024
METRICS = ("ttft_ms", "decode_tps", "cpu_percent_normalized", "peak_rss_mib")


def _obj(properties, *, extra=False):
    return {"type": "object", "required": list(properties), "properties": properties,
            "additionalProperties": extra}


def _number(minimum=0, *, nullable=True, maximum=None):
    result = {"type": ["number", "null"] if nullable else "number", "minimum": minimum}
    if maximum is not None:
        result["maximum"] = maximum
    return result


_TEXT = {"type": "string", "minLength": 1, "maxLength": 180}
_OPTIONAL_TEXT = {"type": ["string", "null"], "minLength": 1, "maxLength": 180}
_ID = {"type": "string", "pattern": r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$"}
_STAMP = {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$"}
_MEASUREMENTS = _obj({
    "ttft_ms": _number(), "decode_tps": _number(),
    "cpu_percent_normalized": _number(maximum=100), "peak_rss_mib": _number(),
})
_SOURCES = _obj({
    **{key: _OPTIONAL_TEXT for key in METRICS},
    "output_tokens": {"type": ["integer", "null"], "minimum": 0},
    "decode_duration_s": {"type": ["number", "null"], "exclusiveMinimum": 0},
    "sample_interval_s": {"type": "number", "exclusiveMinimum": 0},
    "process_count": {"type": "integer", "minimum": 0},
    "process_attribution": {"enum": ["endpoint_owner_and_children", "unavailable"]},
    "cache_policy": _TEXT,
    "prompt_hash": {"type": "string", "pattern": r"^[a-f0-9]{64}$"},
})
_RUN = _obj({
    "run_id": _ID, "prompt_id": {"enum": ["short", "medium", "long"]},
    "repeat_index": {"type": "integer", "minimum": 1, "maximum": 3},
    "timestamp": _STAMP, "status": {"enum": ["ok", "partial", "error"]},
    "measurements": _MEASUREMENTS, "sources": _SOURCES,
    "quality_flags": {"type": "array", "maxItems": 40, "uniqueItems": True,
                      "items": {"type": "string", "pattern": r"^[a-z][a-z0-9_]{0,79}$"}},
    "error": {"type": ["string", "null"], "minLength": 1, "maxLength": 240},
})
_SUMMARY_PROPERTIES = {
    **{key: {"type": "integer", "minimum": 0, "maximum": 9}
       for key in ("runs", "valid_runs", "partial_runs", "failed_runs")},
    **{key: _number() for key in ("median_ttft_ms", "median_tps", "median_cpu_percent", "peak_ram_mb")},
    **{key + "_range": {"type": ["array", "null"], "minItems": 2, "maxItems": 2, "items": _number(nullable=False)}
       for key in METRICS},
    **{key + "_valid_count": {"type": "integer", "minimum": 0, "maximum": 9} for key in METRICS},
}
_SUMMARY = _obj(_SUMMARY_PROPERTIES)
_SUMMARY["properties"] = {**_SUMMARY_PROPERTIES,
    "per_prompt": {"type": "object", "properties": {pid: _obj(_SUMMARY_PROPERTIES) for pid in ("short", "medium", "long")},
                   "additionalProperties": False},
    "method": {"type": "string", "minLength": 1, "maxLength": 600},
    "model": _TEXT, "runtime": _TEXT,
    "machine_label": {"type": "string", "pattern": r"^[A-Za-z0-9][A-Za-z0-9_-]{0,47}$"},
    "warmup_round_trip_s": _number(),
    "note": {"type": "string", "maxLength": 300},
    "quality_flags": {"type": "array", "maxItems": 40, "uniqueItems": True,
                      "items": {"type": "string", "pattern": r"^[a-z][a-z0-9_]{0,79}$"}},
}
_SUMMARY["required"] = list(_SUMMARY_PROPERTIES) + ["per_prompt", "method"]

JSON_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "urn:local-llm-lab:schema:1.0", "title": "Local LLM Lab session (anonymous)",
    **_obj({
        "schema_version": {"const": SCHEMA_VERSION},
        "protocol_version": {"const": PROTOCOL_VERSION},
        "data_kind": {"enum": ["measured", "synthetic"]},
        "session_id": _ID, "created_at": _STAMP,
        "device": _obj({
            "alias": {"type": "string", "pattern": r"^[A-Za-z0-9][A-Za-z0-9_-]{0,47}$"},
            "os": _TEXT, "os_version": _TEXT, "cpu_model": _TEXT,
            "logical_cores": {"type": "integer", "minimum": 1, "maximum": 4096},
            "total_ram_gib": _number(nullable=False), "gpu": _TEXT, "arch": _TEXT,
        }),
        "runtime": _obj({"name": _TEXT, "version": _OPTIONAL_TEXT}),
        "model": _obj({"name": _TEXT, "digest": _OPTIONAL_TEXT,
                       "quantization": _OPTIONAL_TEXT, "acceleration": _TEXT}),
        "config": _obj({
            "temperature": _number(nullable=False, maximum=2),
            "max_output_tokens": {"type": "integer", "minimum": 1, "maximum": 128},
            "repeats": {"type": "integer", "minimum": 1, "maximum": 3},
            "context_tokens": {"type": ["integer", "null"], "minimum": 1},
        }),
        "warmup_round_trip_s": _number(),
        "predictions": _obj({"tps": _number(), "ram_gib": _number()}),
        "runs": {"type": "array", "minItems": 1, "maxItems": 9, "items": _RUN},
        "summary": _SUMMARY,
    }),
}


def _validate(value, schema, location="session"):
    if "const" in schema and value != schema["const"]:
        raise ValueError(f"{location}: unsupported value")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"{location}: unsupported value")
    if "type" in schema:
        allowed = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        kinds = {"null": value is None, "object": isinstance(value, dict),
                 "array": isinstance(value, list), "string": isinstance(value, str),
                 "integer": isinstance(value, int) and not isinstance(value, bool),
                 "number": isinstance(value, (float, int)) and not isinstance(value, bool)}
        if not any(kinds[t] for t in allowed):
            raise ValueError(f"{location}: wrong type")
    if value is None:
        return
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            finite = math.isfinite(value)
        except OverflowError:
            finite = False
        if not finite:
            raise ValueError(f"{location}: non-finite number")
        if "minimum" in schema and value < schema["minimum"]:
            raise ValueError(f"{location}: number below minimum")
        if "maximum" in schema and value > schema["maximum"]:
            raise ValueError(f"{location}: number above maximum")
        if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
            raise ValueError(f"{location}: number below exclusive minimum")
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0) or len(value) > schema.get("maxLength", 100000):
            raise ValueError(f"{location}: invalid text length")
        if "pattern" in schema and not re.fullmatch(schema["pattern"], value):
            raise ValueError(f"{location}: invalid text format")
    if isinstance(value, dict):
        props = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                raise ValueError(f"{location}.{key}: required")
        if schema.get("additionalProperties") is False and set(value) - set(props):
            raise ValueError(f"{location}: unexpected field")
        for key, item in value.items():
            _validate(item, props.get(key, {}), f"{location}.{key}")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0) or len(value) > schema.get("maxItems", 100000):
            raise ValueError(f"{location}: invalid item count")
        if schema.get("uniqueItems") and len({json.dumps(v, sort_keys=True) for v in value}) != len(value):
            raise ValueError(f"{location}: duplicate values")
        for i, item in enumerate(value):
            _validate(item, schema.get("items", {}), f"{location}[{i}]")


def validate_session(document: dict) -> dict:
    """Validate structure and cross-field semantics. Returns the unchanged document."""
    _validate(document, JSON_SCHEMA)
    for stamp in [document["created_at"], *[row["timestamp"] for row in document["runs"]]]:
        try:
            datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("session: invalid UTC timestamp") from exc
    identifiers, pairs = set(), set()
    for row in document["runs"]:
        if row["run_id"] in identifiers:
            raise ValueError("session.runs: duplicate run ID")
        identifiers.add(row["run_id"])
        pair = (row["prompt_id"], row["repeat_index"])
        if pair in pairs or row["repeat_index"] > document["config"]["repeats"]:
            raise ValueError("session.runs: duplicate or out-of-range repeat")
        pairs.add(pair)
        present = sum(row["measurements"][key] is not None for key in METRICS)
        if row["status"] == "ok" and (present != 4 or row["error"] is not None):
            raise ValueError("session.runs: ok requires all four metrics and no error")
        if row["status"] == "error" and row["error"] is None:
            raise ValueError("session.runs: error requires a reason")
        if row["status"] == "partial" and (present == 0 or not row["quality_flags"]):
            raise ValueError("session.runs: partial requires data and a quality flag")
        for metric in METRICS:
            if row["measurements"][metric] is not None and row["sources"][metric] is None:
                raise ValueError("session.runs: measured values require a source")
    return document


def load_session(path: Path) -> dict:
    """Read a bounded JSON session. Eval transcripts and legacy files are rejected."""
    path = Path(path)
    if path.stat().st_size > MAX_SESSION_BYTES:
        raise ValueError("Session exceeds 5 MiB")
    try:
        document = json.loads(path.read_text(encoding="utf-8"),
                              parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Non-finite JSON")))
    except (UnicodeError, json.JSONDecodeError) as e:
        raise ValueError("Invalid session JSON") from e
    validate_session(document)
    # Imported summary text/statistics are not trusted or passed on. Rebuild from
    # the strictly validated records; do not leak arbitrary metadata via exports.
    document["summary"] = canonical_summary(document)
    return document


def safe_alias(alias: str | None, session_id: str) -> str:
    """Use an explicit pseudonym; never derive the alias from the OS account/host."""
    if alias is None or alias == "":
        return "device-" + session_id[:8]
    if not isinstance(alias, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,47}", alias):
        raise ValueError("Device alias must be 1-48 letters, numbers, underscores or hyphens")
    return alias


def _metric_summary(rows):
    result = {"runs": len(rows), "valid_runs": sum(r["status"] == "ok" for r in rows),
              "partial_runs": sum(r["status"] == "partial" for r in rows),
              "failed_runs": sum(r["status"] == "error" for r in rows)}
    for metric, legacy in (("ttft_ms", "median_ttft_ms"), ("decode_tps", "median_tps"),
                           ("cpu_percent_normalized", "median_cpu_percent"), ("peak_rss_mib", "peak_ram_mb")):
        values = [r["measurements"][metric] for r in rows
                  if r["status"] != "error" and r["measurements"][metric] is not None]
        result[legacy] = round(max(values) if metric == "peak_rss_mib" else statistics.median(values), 3) if values else None
        result[metric + "_range"] = [min(values), max(values)] if values else None
        result[metric + "_valid_count"] = len(values)
    return result


def summarize_runs(runs: list[dict]) -> dict:
    """Recompute summaries from records; partial values count only when available."""
    result = _metric_summary(runs)
    result["per_prompt"] = {pid: _metric_summary([r for r in runs if r["prompt_id"] == pid])
                            for pid in ("short", "medium", "long") if any(r["prompt_id"] == pid for r in runs)}
    result["method"] = ("Per-prompt median and range of non-error available values; peak_ram_mb is sampled "
                        "peak RSS in MiB. Decode TPS uses runtime token count / runtime decode seconds; "
                        "TTFT is client-observed first-text latency. Null means unavailable, never zero.")
    return result


def canonical_summary(document: dict) -> dict:
    """A fresh public summary without imported free-text notes or metadata."""
    summary = summarize_runs(document["runs"])
    summary.update(model=document["model"]["name"], runtime=document["runtime"]["name"],
                   machine_label=document["device"]["alias"], warmup_round_trip_s=document["warmup_round_trip_s"])
    summary["note"] = ("SIMULATED EXAMPLE ONLY. Not measured performance or acceptance evidence."
                       if document["data_kind"] == "synthetic" else
                       "Measured local session. CPU excludes GPU work; sampled RSS may include shared pages.")
    summary["quality_flags"] = sorted({flag for row in document["runs"] for flag in row["quality_flags"]})
    return summary
