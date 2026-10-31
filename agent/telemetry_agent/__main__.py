"""CLI entry point. All learner execution uses the same resource/identity gates."""
from __future__ import annotations

import argparse
import json
import sys

from .agent import LabAgent
from .config import Settings
from .llm import LLMError
from .tools import Toolbox


class TextOnlyTools:
    """Evaluation adapter: expose tool contracts but never run inference/actions."""
    def __init__(self, real):
        self.real, self.allow_list = real, real.allow_list

    def schemas(self):
        return self.real.schemas()

    def read_logs(self, text):
        return self.real.read_logs(text)

    def call(self, name, args):
        if name in {"check_hardware", "read_logs", "recommend_model"}:
            return self.real.call(name, args)
        return {"error": "Text-only comparison mode: execution is disabled."}


def main(argv=None):
    p = argparse.ArgumentParser(prog="telemetry_agent")
    p.add_argument("--no-guardrails", action="store_true", help="text-only evaluation only; requires --evaluation-text-only")
    p.add_argument("--evaluation-text-only", action="store_true", help="disable execution tools during a safety comparison")
    p.add_argument("--no-router", action="store_true")
    p.add_argument("--model", help="exact allowed local agent-model tag")
    p.add_argument("--trace", action="store_true")
    sub = p.add_subparsers(dest="cmd")
    t = sub.add_parser("tool", help="run a validated bounded tool")
    t.add_argument("name")
    t.add_argument("args", nargs="?", default="{}", help="JSON object")
    b = sub.add_parser("bench", help="run the standard benchmark through all safety gates")
    b.add_argument("--model", dest="bench_model", required=True)
    b.add_argument("--repeats", type=int, default=3)
    b.add_argument("--guess-tps", type=float)
    b.add_argument("--guess-ram-gb", type=float)
    b.add_argument("--tester", default="", help="deprecated; personal tester labels are not exported")
    b.add_argument("--machine-label", help="deprecated; the collector generates an anonymous device alias")
    args = p.parse_args(argv)
    if args.no_guardrails and not args.evaluation_text_only:
        p.error("--no-guardrails requires --evaluation-text-only; no live execution comparison.")
    try:
        settings = Settings(guardrails=not args.no_guardrails, router=not args.no_router,
                            **({"agent_model": args.model} if args.model else {}))
        tools = Toolbox(settings)
        if args.cmd == "tool":
            if len(args.args) > 64 * 1024:
                raise ValueError("Tool JSON exceeds 64 KiB.")
            out = tools.call(args.name, json.loads(args.args))
            print(json.dumps(out, indent=2, default=str, allow_nan=False))
            return 1 if "error" in out or (args.name == "run_benchmark" and out.get("failed_runs", 0) > 0) else 0
        if args.cmd == "bench":
            if args.evaluation_text_only:
                raise ValueError("Benchmarks are disabled in text-only evaluation mode.")
            if args.tester or args.machine_label:
                print("Personal labels are omitted; the export uses an anonymous device alias.", file=sys.stderr)
            out = tools.run_benchmark(args.bench_model, repeats=args.repeats,
                                      guess_tps=args.guess_tps, guess_ram_gb=args.guess_ram_gb)
            print(json.dumps(out, indent=2, default=str, allow_nan=False))
            if out.get("failed_runs", 0):
                print("Benchmark recorded failed requests. Inspect the saved error records; this run did not pass.", file=sys.stderr)
            elif out.get("partial_runs", 0):
                print("Benchmark recorded partial measurements. Inspect quality flags; complete acceptance is not established.", file=sys.stderr)
            return 1 if "error" in out or out.get("failed_runs", 0) > 0 else 0
        tools.ensure_model_ready(settings.agent_model)
        agent = LabAgent(settings, toolbox=TextOnlyTools(tools) if args.evaluation_text_only else tools)
    except (ValueError, TypeError, LLMError, OSError) as exc:
        p.exit(2, f"Supported stop: {exc}\n")
    mode = "text-only comparison" if args.evaluation_text_only else "manual lab; safety on"
    print(f"Local lab assistant ({settings.agent_model}; {mode}). Type 'quit' to exit.\n")
    while True:
        try:
            text = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if text.lower() in {"quit", "exit"}:
            return 0
        if not text:
            continue
        if len(text) > 6000:
            print("Use a message shorter than 6000 characters.")
            continue
        try:
            tools.ensure_model_ready(settings.agent_model)
            reply = agent.ask(text)
        except (LLMError, ValueError, RuntimeError) as exc:
            print(f"[supported stop] {exc}\n")
            continue
        if args.trace:
            for step in reply.trace:
                print(f"  [{step['chosen_by']}] {step['tool']}({json.dumps(step['args'])})")
        if reply.guardrail_intervened:
            print("  Safety layer changed an unsafe draft.")
        print(f"\nassistant> {reply.text}\n")


if __name__ == "__main__":
    sys.exit(main())
