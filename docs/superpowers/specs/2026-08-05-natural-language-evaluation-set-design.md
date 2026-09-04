# Natural-language Evaluation Set Design

## Goal

Replace the mixed 76-question evaluation corpus with a 50-question Korean
natural-language corpus that represents an employee asking the internal-policy
chatbot practical questions.

## Product scope

- The benchmark measures the employee-facing chatbot, not direct regulation
  navigation by article number.
- Every question must be answerable from `datasets/docs/regulations.md`.
- Every row must retain an expected parent-article identifier so retrieval can
  be measured independently of answer quality.
- The corpus must contain no explicit article-number lookup wording such as
  `제32조에 따라`.

## Dataset design

- Replace `datasets/eval/qa_set.jsonl` with exactly 50 JSONL records.
- Retain the 41 existing records whose `type` is `일상어`, after renumbering
  records consecutively from `q01` through `q41`.
- Add nine new employee-natural questions to cover underrepresented practical
  policies: annual-leave request timing, remote-work approval, travel-expense
  settlement, expense evidence, personal-data handling, work-vehicle booking,
  remote-system VPN access, password rules, and document retention.
- All records use `type: "일상어"` and exactly these keys: `id`, `type`,
  `question`, `gold_jo`, `answer`.
- Every `gold_jo` must reference a parent article contained in the regulation
  corpus. Questions and gold answers are written from the regulation text, not
  invented company practices.

## Verification

- Update the existing evaluation-loader contract test for 50 consecutive IDs
  (`q01` through `q50`) and the all-natural-language condition.
- Add a dataset-integrity test that rejects article-number query wording and
  verifies each referenced `gold_jo` exists in `regulations.md`.
- Run the focused evaluator/export tests and the full project suite. Existing
  failures unrelated to this change must be reported separately.

## Non-goals

- Do not add an article-number diagnostic dataset in this change.
- Do not alter RAG retrieval, Qwen prompting, embedding, or Qdrant behavior.
- Do not report a new accuracy number until the new 50-question corpus has
  been run through the actual RAG pipeline.
