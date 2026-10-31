# Local AI Lab learning portal

A buildless, dependency-free teaching and interpretation interface. It has four views:

- **Learn:** six concept explanations and an optional ten-item pre/post knowledge check.
- **Deploy:** manual Windows and macOS instructions, with commands learners run themselves in their own account.
- **Predict & Run:** numeric TPS/RAM hypotheses and a controlled benchmark protocol.
- **Results:** local JSON imports, device/model/prompt/data-kind filters, four metric summaries, median/range SVG charts, per-session conditions, source methods, quality flags, and prediction comparisons.

## Preview

From the repository root, with Python installed:

```text
python3 -m http.server 8000 --bind 127.0.0.1 --directory portal
```

On Windows, use `py -3` in place of `python3`. Open `http://127.0.0.1:8000`. Opening `index.html` directly also supports the learning content and manual file imports, but the example-loading button requires an HTTP server. Static hosting can serve this directory as-is; no API or build step is required.

## Local helper bridge

The public portal **does not call localhost**, inspect hardware, execute commands, run a model, or upload files. Launch the separate Python helper from `agent/` and use its printed local URL, including its session fragment. Export one JSON session per benchmark, then choose **Import JSON** here. The portal accepts the versioned contract in `docs/schema-v1.json`; it does not accept the older CSV format or the separate learning-record export.

`examples/synthetic-macos.json` and `examples/synthetic-windows.json` contain invented data. The `synthetic-session.json` alias duplicates the macOS example and is intentionally rejected if imported alongside it. Examples are clearly identified as synthetic in banners, chart labels, session records, and tables. They must not be presented as real hardware tests.

## Data handling and interpretation

- Files are processed in browser memory only. Reloading clears benchmark imports.
- Maximum 5 MiB per file, 30 sessions, and nine runs per session. Unsupported versions, malformed fields, non-finite or out-of-range numbers, invalid dates, duplicate IDs, and duplicate prompt/repeat pairs are rejected.
- A schema-valid file is not proof of authenticity or accuracy. `measured` is the source file's declaration.
- Statistics are recomputed from run records; imported `summary` values are ignored.
- Failed runs contribute no metric values. Partial runs contribute available values per metric. `null` stays missing; numeric zero remains zero. Sample counts reflect those exclusions.
- Metrics show medians of the selected run values, with minimum–maximum ranges. RAM summarizes per-run observed RSS peaks. Prediction RAM is converted using 1 GiB = 1024 MiB.
- Multiple conditions produce descriptive pooled medians only. Use filters and session charts before drawing comparisons. Model digest, runtime, quantization, context, output cap, repeat count, and cache policy remain visible in the records.
- CPU is normalized to logical cores and is not GPU utilization. RSS is process memory, not dedicated GPU memory or total system use; shared pages can be counted twice.
- The TTFT proxy is client-observed request start to the first non-empty response text. Streaming chunks are not verified token boundaries.

## Optional learning record

Quiz results and numeric predictions stay in memory by default. A learner can opt into storing them in this browser; switching the option off removes the stored record. **Clear saved learning data** removes the stored record and in-tab quiz/prediction state. The anonymous learning export contains answers, scores, quiz completion times, and numeric predictions—no names, benchmark imports, or free-text reflections. The quiz is a teaching exercise, not a validated instrument or a causal measure of learning gain; repeating questions can create practice effects.

## Tests

With Node.js 20 or newer, from the repository root:

```text
node --test portal/tests/*.test.js
```

Tests cover the actual synthetic fixtures, missing and failed values, zeros, filters, summary recomputation, duplicate records, schema/version/date/source validation, non-finite values, and oversized or malformed files. No model, runtime, packages, or network are needed.

For browser acceptance, check all four views at desktop and mobile widths; complete both quizzes; toggle storage and reload; export/clear learning data; load examples twice to exercise deduplication; filter all four dimensions; import valid, malformed, oversized, duplicate, and unavailable-metric exports; and confirm keyboard navigation, visible focus, readable chart alternatives, no horizontal page overflow, and no browser errors or localhost/API calls.

## Implementation

`data.js` is the pure browser/CommonJS data layer and `app.js` owns UI state. All imported text is inserted with `textContent` or DOM text nodes; no imported HTML is interpreted. Charts are native SVG with exact-value text alternatives. The page uses no CDN, external fonts, analytics, or third-party requests. CSP restricts resources to the same origin. It does not disable browser security features.
