# Local lab assistant and collector

Start with the repository [quick start](../README.md). Run commands from this directory with a project virtual environment. The helper is available before a model is installed and exposes manual deployment checks, predictions, inference, and anonymous JSON download.

- `telemetry_agent.helper`: loopback-only browser helper, ephemeral API token, bounded actions.
- `telemetry_agent`: CLI chat, validated tools, and resource-gated benchmarks.
- `skill/`: teaching playbook, explicit model allow-list, safe error catalog.
- `telemetry_agent/collector.py`: one warm-up, fixed short/medium/long prompts, three repeats, native decode timing and process attribution.
- `telemetry_agent/protocol.py`: strict versioned anonymous result contract.
- `tests/`: unit and fake-loopback integration tests; no model download required.

Example benchmark using the environment's interpreter:

```text
python -m telemetry_agent bench --model qwen2.5:1.5b --repeats 3 --guess-tps 20 --guess-ram-gb 2
```

Set `AGENT_MODEL` when changing the chat model. `AGENT_BASE_URL` defaults to `http://127.0.0.1:11434/v1`; external runtime endpoints are rejected. Use `RUNTIME_INSTALL_DIR` for a whole portable runtime directory and `OLLAMA_MODELS` for its actual model location. The entire resource inventory must be known before inference. Read tool output for supported stop conditions instead of bypassing checks.

JSON is the portal exchange format. The compatibility CSV is local convenience, not the teaching portal input. Results remain in `results/` and are Git-ignored. Review aliases and metadata before sharing elsewhere. Logs and chat stay in the helper session; do not paste secrets or private documents.

The old [DEMO.md](DEMO.md), [EVAL_RESULTS.md](EVAL_RESULTS.md), and `evals/` are retained as historical development material. Their earlier installation shortcuts, CSV dashboard assumptions, and scores do not supersede the current root README, source, or evaluation protocol. Use no security bypass or administrator installation workaround.
