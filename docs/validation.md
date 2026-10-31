# Verification record

This record separates implementation checks from acceptance evidence. It does not claim that every project outcome has already been achieved.

## Local checks,2026-10-31

- Python3.13.2 on macOS, psutil7.2.2:98 backend unit/integration tests passed. These include real loopback fake-HTTP servers, strict tool-call parsing, native decode-token/duration handling, failed/partial attempts, process attribution, OS/thread locks, export privacy, Host/Origin/token checks, proxy/redirect rejection, complete-installation budget gates, and safe manual deployment behavior.
- Node25.8.1:13 portal tests passed, covering the actual synthetic files, schema/version/units, finite metrics, source/status/date checks, duplicates, missing versus zero, filters and recomputation, malicious summaries and oversized input.
- Six independent-review scorer tests and the project contract checks passed locally and are included in CI. Blank judgments remain pending; no rubric acceptance score is inferred from unit tests.
- Chrome desktop: inspected Learn and Results visually; loaded synthetic examples, filtered device/prompt to three runs, and completed the ten-question quiz with a10/10 score using the visible answers. This verifies UI behavior, not an observed learning gain. The local helper opened through a tokenized launch link, completed the hardware check without model inference, and displayed the failed experiment as0 complete /0 partial /9 errors with missing metric values. A top-level navigation regression found during this check was fixed without relaxing cross-site API rejection.

## Actual local runtime attempt

The pre-existing Ollama0.7.0 executable crashed in this environment during GPU initialization. An official portable Ollama0.40.13 distribution was then started in an isolated work directory, with existing Llama3.2:3b Q4_K_M model weights referenced without modifying the user's original model store. The metadata API responded, but real inference failed when its runner could not allocate a Metal context/buffer. An explicit CPU-only request also returned HTTP500. No OS protections were disabled and no administrator workaround was used.

The collector retained all nine baseline error rows with a `warmup_failed` flag; it made no successful measured requests after the failed warm-up. All four metrics are null. This is a correctly reported failed experiment, **not** a successful performance benchmark. Raw runtime logs and local paths remain private and Git-ignored. The process sampling environment also denies full child-process enumeration; the implementation handles that boundary with missing metrics rather than reporting only the small parent server's memory.

Inference and complete four-metric acceptance need a normal supported user terminal/device outside these restrictions. A one-case benign collection smoke test retained a model-request error and marked the suite incomplete. The real-model diagnosis and guarded/unguarded answer-quality suites have not passed independent human review. Fake-HTTP integration verifies the transport and calculation path but cannot substitute for model quality or hardware performance.

The browser extension did not permit selecting local files, so the native file-chooser import interaction remains pending; its validation/data path was checked separately against the actual retained error session. No extension permission was changed.

## Remaining acceptance evidence

| Requirement | Status and next evidence |
| --- | --- |
| Real macOS local inference and nine valid four-metric runs | Pending; current isolated attempt failed as described above. Record a supported normal-user device run. |
| Real Windows installation/inference and nine valid four-metric runs | Pending physical-device test. Windows CI tests software behavior only. |
| Whole installation at or below provisional10 GiB | Gate implemented. Verify the full chosen runtime distribution, Python/project, all model files, free disk and current RAM on each target device. No universal fit claim. |
| At least16/20 diagnosis answers with correct cause and safe actionable fix |20 candidates and human review tooling ready; no independently reviewed acceptance score yet. |
| Guarded0/15 unsafe suggestions versus unguarded comparison |15 prompts and text-only dual-mode collection ready; independent safety/helpfulness review pending. |
| Five novice pilots,4/5 completion, paired quiz targets | Instruments and private record templates ready; recruitment, consent, observation and analysis pending. |
| Prepared workflow timing and first-inference timing | Pending timed novice runs; count downloads/setup separately and preserve failures. |
| Mobile layout,assistive technology and multi-browser acceptance | Responsive CSS and semantic controls implemented; dedicated device/browser matrix pending. |

Do not present invented example values, historical demo catalog scores, clean pattern-check output, or generated UI test scores as client acceptance evidence. Freeze the final protocol and scoring key, record every attempt, and have reviewers inspect both failures and successes.
