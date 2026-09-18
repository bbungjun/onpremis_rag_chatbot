# Intent classification accuracy evaluation design

## Problem

`scripts/eval_intent.py` currently reports how often the rule-based interpreter returns
`general_qa`. That is coverage, not accuracy: `general_qa` can be the correct label for a factual
or underspecified question, while a non-general label can still be wrong. The current 69.4%
coverage result therefore cannot answer “how often is the selected intent correct?”

## Goal

Measure a reproducible baseline for the current five-label classifier without changing the
classifier itself:

```text
deadline_lookup
eligibility_check
procedure_lookup
requirement_lookup
general_qa
```

The report must include overall accuracy, correct/total counts, type-level accuracy, a confusion
matrix, and every misclassified case. Existing coverage output must remain available.

## Gold-label policy

Gold labels are reviewed against the user’s primary information need and the canonical prompt
that should help answer it. They are not copied from the current classifier output.

```text
deadline_lookup    time, deadline, duration, cadence, or date lookup
eligibility_check  whether a concrete action or situation is allowed or satisfies policy
procedure_lookup   steps, channel, reviewer, approver, or reporting route
requirement_lookup required conditions, evidence, documents, or configuration
general_qa         factual/count/consequence lookup outside the four prompts, or underspecified input
```

When a question could support more than one label, annotate the primary request expressed in the
question. An underspecified transformation may legitimately become `general_qa` even when its
source question had a specialized intent.

## Data design

Add `datasets/eval/intent_gold.jsonl` as an annotation layer containing `id` and
`expected_intent` for all 98 current evaluation questions. Keeping labels separate avoids changing
the retrieval evaluation schema and makes reviewer-authored labels distinguishable from classifier
outputs. The initial annotation is authored by the implementation agent and is not an independent
human judgment; the reported accuracy is therefore a provisional development baseline.

The evaluator joins by case `id`. It rejects missing IDs, duplicate IDs, invalid intent values,
missing gold labels for evaluated cases, and duplicate case IDs. Extra gold labels may remain so a
subset of cases can be evaluated with the same gold file.

`intent_robustness.jsonl.base_id` is not used for scoring. Several values refer to IDs from the
superseded 76-question dataset, so inheriting labels through that field would silently corrupt the
baseline. Each robustness question receives an independent reviewed label.

## Interfaces

`scripts/eval_intent.py` gains:

```text
load_gold_labels(path) -> dict[id, expected_intent]
evaluate_accuracy(cases, gold_labels) -> AccuracyReport
print_accuracy_report(report, list_errors=False)

CLI:
  --gold datasets/eval/intent_gold.jsonl
  --list-errors
```

The existing `summarize` and `--list` coverage behavior stays backward compatible.

## Metrics

```text
accuracy = correct predictions / gold-labeled evaluated questions
by-type accuracy = correct / total for each existing dataset type
confusion[expected][actual] = case count
```

This is a single-annotator development baseline, not an independently human-reviewed or held-out
model-quality result. No statistical significance or downstream answer-quality improvement will be
claimed.

## Verification

- Write evaluator contract tests before implementation and observe failure.
- Run targeted evaluator and dataset-contract tests in Docker.
- Run the CLI on the 98 cases and preserve the exact output.
- Run the full Docker test suite, Qdrant check, and application healthcheck.
- Record measured results and limitations in a portfolio document.
