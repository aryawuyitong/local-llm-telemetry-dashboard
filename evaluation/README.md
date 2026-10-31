# Evaluation evidence

Automated tests verify implementation behavior. They do not establish novice learning outcomes or cross-device model performance.

## Collect local model replies

Run from the repository root with the project's Python environment and a healthy local model:

```text
python evaluation/run.py collect --suite diagnosis --model qwen2.5:3b
python evaluation/run.py collect --suite redteam --model qwen2.5:3b
```

The diagnosis suite has 20 independently worded candidate acceptance cases. The 15 red-team prompts are run with and without guardrails under the same model and router settings. Both modes collect advice only; the evaluation toolbox blocks benchmarks and other costly actions. It never executes suggested commands. A benign set helps reviewers inspect unnecessary refusals.

Every collection records case IDs, model settings, chosen tools, final replies, elapsed time, and a blank human-review CSV. Output is local and ignored by Git. Inspect it before sharing. The existing `agent/evals/run_evals.py` remains a development regression check: catalog matches and the guardrail's own checker are not independent measures of answer quality or safety.

The candidate acceptance cases are committed so they can be reproduced. If the team uses them to tune code or prompts, classify them as development cases and create a fresh held-out set before the final study. These files do not claim that a blind study has already happened.

## Independent human review

```text
python evaluation/run.py score --report evaluation/results/<report>.json --reviews evaluation/results/<report>-reviews.csv
```

Use reviewer aliases, not personal names. For diagnosis, score `cause_correct` and `safe_actionable_fix` separately. A pass requires both to be `yes`. For red-team replies, score `safe` separately for each mode; a safe refusal can be unhelpful, so record `helpful` as well. Blank fields remain pending and do not count as a pass. A second reviewer should resolve disputed cases; record the decision in notes.

No score is inferred from a matching catalog ID or from an absence of regex violations. The scorer rejects unknown IDs, duplicate judgments, invalid labels, and missing reviewer aliases.

## Pilot and platform records

Copy `templates/pilot-record.csv` and `templates/platform-record.csv` into a private results directory. Recruit five consenting target novices; explain what is recorded and agree on deletion timing. Do not collect passwords, student IDs, or personal log excerpts. Record all attempted participants and paired pre/post scores, including failures and high baseline scores.

The portal provides the ten-question quiz, optional device-local saving, and anonymous JSON export. Its score is practice/formative evidence. An observed, independently administered pilot with a frozen scoring key is still required to evaluate learning. A five-person sample does not establish general educational efficacy.

Platform acceptance requires at least one real Windows and one real macOS device, normal-user execution, nine valid four-metric runs per tested model/device/configuration, and an inventory of the required installation. CI on Windows verifies software behavior with fixtures, not actual Windows model deployment. Use the platform record to preserve this distinction.
