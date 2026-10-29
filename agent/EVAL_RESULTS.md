# Evaluation results: first run (2026-10-26)

**Setup:** Apple M5, 16 GB RAM, macOS 27 · agent model `qwen2.5:3b` via Ollama 0.33 · router + guardrails on unless noted.
Transcripts: `results/evals_*.json`. Re-run with `python evals/run_evals.py all`.

## Against the scope's targets
| Metric | Target | Result | Notes |
|---|---|---|---|
| Agent diagnosis (20 scripted failures) | ≥ 16 / 20 | **20 / 20** | Was 18/20 before the router also checked the catalog (two errors had no "error" words) |
| Guardrails (15 red-team prompts) | 0 unsafe (vs. without) | **0 / 15** with · **5 / 15** without | Without: admin ×3, delete ×1, security_off ×2. A first run gave 6/15 without; model output varies a little |
| Benchmark collector | 4 metrics as a standard user | ✅ macOS | Windows not tested yet |
| Recommendation fits budget | 100% of test laptops | ✅ 1 laptop | Needs the other laptops |

## Sample benchmark (qwen2.5:3b, 3 prompts × 3 repeats)
| Prompt | TTFT (ms) | TPS | CPU % | Peak RAM (MB) |
|---|---|---|---|---|
| short | ~200 | ~25 | ~14 | ~2,115 |
| medium | ~215 | ~23 | ~15 | ~2,120 |
| long | ~400 | ~22.5 | ~7 | ~2,140 |
The longer prompt roughly doubles TTFT (more prompt to process) but barely changes TPS: a good teaching example.

## What we fixed because of testing
1. **Wrong RAM numbers (45 MB):** Ollama runs inference in a child `llama-server` process; the collector now includes it.
2. **Unrealistic repeat TTFT (~36 ms):** the runtime cached identical prompts; each run now gets a unique tag.
3. **LLM skipped or misused tools:** without the router, the 3B model answered a port error from memory (Windows commands on a Mac, force-killing processes) and reported a learner's *guess* of 40 tok/s as a result. Added the router, an OS line in the system prompt, fact-grounding rules, and clearer field names.
4. **Under-recommending:** free RAM swings a lot on macOS, so planning now uses max(free, half of total) with a "close apps first" warning.
5. **Secrets:** "my password is …" wasn't redacted (pattern only caught `password:`); fixed, and the agent now tells the learner to revoke/change any pasted secret.

## Limitations (say these in the final README)
- The 20 failures were written to match the catalog, so 20/20 mostly shows the routing and explanation work. **Real errors from our own installs are the honest test.**
- The red-team check uses the **same rules** as the guardrail, so "0 unsafe" means "0 replies that break our rules". Hand review found unsafe replies were correctly flagged, but some *safe* replies were unhelpful (e.g. answering a permissions question with a hardware summary).
- One machine, one agent model, one runtime. Windows and llama.cpp are untested.
- Quality of explanations wasn't scored; the pilot users and the 10-question quiz cover that.
