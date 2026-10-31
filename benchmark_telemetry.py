"""Compatibility entry point: use the shared, validated collector instead of chunk counting."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / 'agent'))
from telemetry_agent.__main__ import main

if __name__ == '__main__':
    if len(sys.argv) == 1:
        print('Use: python benchmark_telemetry.py bench --model qwen2.5:1.5b --repeats 3')
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1:]))
