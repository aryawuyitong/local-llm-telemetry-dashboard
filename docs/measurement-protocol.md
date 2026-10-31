# Measurement protocol v1

Baseline: Ollama native `/api/chat`, exact approved local tag, recorded runtime version and digest. The compatible chat endpoint is used for advice, not as a source of invented decode timing. llama.cpp execution is pending a trusted manifest and timing adapter.

1. Record OS/architecture, logical cores, RAM, runtime/model metadata, configuration, and numeric TPS/RAM predictions. Use the full-budget and currently available memory gates.
2. Close optional competing workloads yourself if desired, record power/thermal/background conditions privately, and keep them consistent. No tool kills processes.
3. Send one short warm-up request. Record its end-to-end duration as `warmup_round_trip_s`; it is not isolated model-load time. Exclude it from measured medians. A failed warm-up yields retained error rows and a supported failure summary.
4. Use the fixed prompts defined in collector source, short/medium/long, sequentially repeated three times. Temperature0, max128 output tokens, context2,048. No concurrency. One measured session has nine attempts. Shortened repeat counts are development tests, not baseline acceptance.
5. Time request start with a monotonic clock and detect the first nonempty text event. Export its milliseconds as a **TTFT proxy**. HTTP framing can combine tokens; this does not prove true tokenizer-first-token latency.
6. Calculate decode TPS from native `eval_count / (eval_duration / 1e9)`. Do not count stream events as tokens and do not substitute wall-clock request duration. Missing or invalid native timing means null TPS.
7. Sample the runtime listener and refreshed children approximately every100ms. Normalize aggregate CPU-time deltas to elapsed time and logical core count. Sum attributable RSS and retain the highest observed sum per run. Short-lived allocations between samples can be missed; shared pages can be counted twice. CPU excludes GPU work; RSS does not measure dedicated VRAM. Missing/incomplete process attribution yields unavailable metrics and explicit flags.
8. Export one strict schema1.0 session, retaining all error/partial attempts. Review alias and metadata, then import it into Results. Failed rows contribute no statistics; partial rows contribute only present metric values. Zero is valid, null is missing. Compute each metric median, range, and available sample count, with per-session/per-prompt comparisons.

Ollama keeps the model resident for five minutes and may reuse prompt caches across repeated requests. The recorded cache policy is uncontrolled runtime caching; the protocol does not claim cold-cache or independent trials. Compare matching digest, runtime, acceleration, context, output cap and prompt class, then discuss residual cache/thermal differences. Do not merge synthetic and measured data as study evidence.

Sources: [Ollama native chat metadata](https://docs.ollama.com/api/chat) defines output token count and decode duration; [running model metadata](https://docs.ollama.com/api/ps) supplies reported residency and execution configuration. File sizes in the model catalog are estimates; actual runtime inventory and whole-installation bytes govern resource gates.
