"""Command line entry point.

    python -m telemetry_agent                      chat with the lab assistant
    python -m telemetry_agent --no-guardrails      same, with the safety layer off (for the comparison)
    python -m telemetry_agent tool check_hardware  run one tool directly and print its JSON
    python -m telemetry_agent tool read_logs '{"log_text": "No space left on device"}'
    python -m telemetry_agent bench --model qwen2.5:1.5b --tester Rohan --repeats 3
"""
from __future__ import annotations

import argparse
import json
import sys

from .agent import LabAgent
from .collector import run_benchmark
from .config import Settings
from .llm import LLMError
from .tools import Toolbox


def main(argv=None):
    p = argparse.ArgumentParser(prog="telemetry_agent")
    p.add_argument("--no-guardrails", action="store_true", help="turn the safety layer off")
    p.add_argument("--no-router", action="store_true", help="let the LLM choose every tool itself")
    p.add_argument("--model", help="agent model (default: AGENT_MODEL or qwen2.5:3b)")
    p.add_argument("--trace", action="store_true", help="print each tool call")
    sub = p.add_subparsers(dest="cmd")
    t = sub.add_parser("tool", help="run one tool")
    t.add_argument("name")
    t.add_argument("args", nargs="?", default="{}", help="JSON object of arguments")
    b = sub.add_parser("bench", help="benchmark a model")
    b.add_argument("--model", dest="bench_model", required=True)
    b.add_argument("--repeats", type=int, default=3)
    b.add_argument("--tester", default="")
    b.add_argument("--machine-label")
    args = p.parse_args(argv)

    settings = Settings(guardrails=not args.no_guardrails, router=not args.no_router)
    if args.model:
        settings.agent_model = args.model

    if args.cmd == "tool":
        print(json.dumps(Toolbox(settings).call(args.name, json.loads(args.args)), indent=2, default=str))
        return
    if args.cmd == "bench":
        print(json.dumps(run_benchmark(args.bench_model, settings, repeats=args.repeats,
                                       tester=args.tester, machine_label=args.machine_label), indent=2))
        return

    agent = LabAgent(settings)
    mode = "ON" if settings.guardrails else "OFF"
    print(f"Local LLM lab assistant ({settings.agent_model}, guardrails {mode}). Type 'quit' to exit.\n")
    while True:
        try:
            text = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if text.lower() in ("quit", "exit"):
            return
        if not text:
            continue
        try:
            reply = agent.ask(text)
        except LLMError as e:
            print(f"[error] {e}\n")
            continue
        if args.trace:
            for step in reply.trace:
                print(f"  · [{step['chosen_by']}] {step['tool']}({json.dumps(step['args'])})")
        if reply.guardrail_intervened:
            print("  · guardrail rewrote an unsafe draft")
        print(f"\nassistant> {reply.text}\n")


if __name__ == "__main__":
    sys.exit(main())
