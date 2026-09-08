# Fixed-context intent ablation

## Before and question

Intent label agreement (39/98 with AI-authored provisional labels) does not measure RAG answer
quality. Test whether current canonical-question instructions improve answers over the original
question, and whether overriding the predicted label offers further benefit.

## Experimental contract

- A/no_intent: original question also occupies the canonical_question slot.
- B/predicted_intent: existing interpreter's canonical question.
- C/gold_intent: existing canonical builder with the provisional expected intent and the SAME
  extracted conditions. This is an expected-label intervention, not an oracle answer.
- All share the existing SYSTEM_PROMPT and injection guard; no additional A-only prompt.
- Retrieve ONCE per question using lightly normalized original text, without intent rewriting.
  Freeze RRF top-k parents; trim against the longest of all three prompts, jointly. Fail when one
  parent still cannot fit the current character-budget heuristic; do not silently vary contexts.
- Save exact prompts and hashes. Equal predicted/gold labels must produce identical B/C inputs.
- Qwen is only used to generate answers from these retrieved chunks. No Qwen classification/judge.
- Models run sequentially: bge-m3 preparation -> Qwen generation -> EXAONE judging. Unload the
  experiment model at phase boundaries; never stop unrelated desktop apps.
- Fixed temperature/settings; same seed per question/repetition; rotate all six arm orders across
  cases. Record duration, load duration, prompt/output token counts, truncations and /api/ps.
- 98 questions, one initial run per arm (294 requests). Repetition count is configurable; no
  significance or generalization claim from this development-set single run.

## Labels and endpoints

Freeze existing gold definitions and prompts: the broad date/cadence gold definition does not
exactly match the existing deadline prompt. C therefore tests current prompt templates under
provisional labels, NOT perfect semantic understanding. Do not tune after seeing answers.

Primary cohort: 50 qa_set cases with reference answers. Exploratory cohort: 48 robustness cases,
including 12 ambiguous questions; no inheritance from stale base_id. Judge these against frozen
context only and report separately. Independent human annotation/answer evaluation remains needed.

EXAONE sees original question, frozen context, optional reference and ONE candidate, without arm
or intent labels. Grade correctness, context groundedness and completeness 0..2. When context is
insufficient, reward an appropriately limited answer. A correct reference fact unsupported by
context cannot earn groundedness. Ambiguous requests should clarify or explicitly qualify.
Store all raw judge attempts; invalid JSON is an error, never a zero or excluded without counts.

Paired comparisons B-A/C-A/C-B use ONLY complete scored triplets; report eligible/complete counts,
score means, wins/ties/losses, and mean differences. Separately report fallback, generation errors,
truncation, citation heuristics and retrieval source recall. Identical source recall across arms
is an invariant, not evidence of answer improvement. No-intent here still has the common system
instructions and normalization; it does not mean disabling the whole interpreter in production.

## Artifacts and implementation

Evaluation-only app/intent_ablation.py and scripts/compare_intent.py; no production route changes.
Stage commands prepare/generate/judge/summary; reports/local-judge/intent-ablation/<run>/ holds
input hashes, snapshots, durable append-only answers/judgments and JSON summary. Resume skips
finished records, refuses conflicting artifacts/configuration, and never overwrites a run.
Do not track raw context, answers, secrets or endpoint credentials. Publish aggregate portfolio
evidence, exact commands, failures and limitations. Existing pytest is regression evidence only.

## Observed transport failure and revision

Plain JSON instructions produced six failed verdicts (capitalized keys, rationale outside JSON).
Keep those raw attempts. Version `schema-v2` enforces the four-field Ollama JSON schema with the
same grading criteria and frozen answers. Versioned judge configs pin answer/context hashes and
the runner hash. Rejudging may use a changed runner; dataset, interpreter, prompt builder, core
experiment code and context snapshots still must match. Generation resume remains strict.
