# Local LLM Judge Evaluation Design

## Goal

Provide a reproducible, fully local evaluation runner for the internal-policy
RAG chatbot. The runner must answer the existing 76 gold-question cases, have
a separate local judge model assess each answer, and write aggregate metrics
for resume-ready before/after experiments.

## Scope

- Read `datasets/eval/qa_set.jsonl`; its 76 rows contain a question, a gold
  answer, and the expected parent article IDs (`gold_jo`).
- Generate each candidate answer through the existing `app.rag_pipeline`
  using the configured Qwen answer model.
- Require the explicitly allowlisted local Judge model `exaone3.5:7.8b`
  through `--judge-model`. Qwen remains limited to RAG answer generation, as
  required by the project rules. An exact allowlist also prevents Qwen aliases
  or custom names from bypassing that rule.
- Ask the Judge to return validated JSON with three 0-to-2 scores:
  `correctness`, `groundedness`, and `completeness`, plus a concise Korean
  rationale.
- Calculate `source_recall` deterministically from returned source IDs and
  each case's `gold_jo`, independently of the Judge.
- Append and flush one JSONL record per completed case, write immutable run
  metadata (timestamp, model names, settings, case count, and dataset SHA-256),
  and produce a human-readable Markdown summary with counts, means, source
  recall, and bounded answer/Judge failure examples.
- Keep reports under `reports/local-judge/`, which must be ignored by Git.

## Non-Goals

- Do not replace the production answer pipeline or expose Judge scoring in the
  chatbot UI.
- Do not add cloud judging, RAGAS, vector-store changes, or new dependencies.
- Do not automatically install or download Ollama models.
- Do not claim a benchmark result until Ollama, Qdrant, embeddings, and the
  selected local Judge model are available and the runner has completed.

## Components

### `app/local_judge.py`

Owns the Judge prompt, strict JSON parsing, response validation, and the
`JudgeVerdict` value object. It calls the existing Ollama chat client with a
separate Judge system prompt. The prompt treats the policy answer, reference
answer, question, and retrieved-source metadata as untrusted data, and never
as instructions.

The parser rejects malformed JSON, non-object responses, missing fields,
non-integer scores, scores outside 0..2, and empty rationales. This turns a
malformed model response into a visible case failure rather than silently
making an optimistic score.

### `scripts/evaluate_local_judge.py`

Owns CLI orchestration. It loads the evaluation cases, runs the existing RAG
answer function, invokes `app.local_judge`, calculates source recall, and
writes timestamped report files. It accepts `--judge-model`, `--top-k`,
`--limit`, and `--output-dir`; `--judge-model` is required and must exactly
match the controlled `exaone3.5:7.8b` allowlist. The CLI permits
`--output-dir` only beneath `reports/local-judge/`, preventing report data
from being accidentally written to a tracked or shared path.

Each result record includes only experiment settings, case ID and type, model
names, scores, elapsed times, generated answer, and returned source IDs. An
answer failure is recorded as `answer_error`; a Judge failure is recorded as
`judge_error` while retaining the generated answer and deterministic source
recall. It does not record environment variables, credentials, or full
retrieved policy text. Reports remain local and Git-ignored because answers
can contain policy content.

### `tests/test_local_judge.py` and `tests/test_evaluate_local_judge.py`

Unit tests use injected answer and chat callables to keep CI independent of a
running Ollama or Qdrant instance. They cover prompt construction, strict
Judge-response validation, score aggregation, source recall, report content,
and rejection of Qwen as a Judge model.

## Data Flow

```text
qa_set.jsonl case
  -> app.rag_pipeline.answer_question (Qwen answer generation)
  -> returned answer + source IDs + gold answer
  -> app.local_judge (separate local Judge model)
  -> deterministic source recall + Judge scores
  -> reports/local-judge/<timestamp>/{run.json, results.jsonl, summary.md}
```

## Score Definitions

| Field | Range | Meaning |
| --- | --- | --- |
| `correctness` | 0-2 | Whether the answer agrees with the gold answer. |
| `groundedness` | 0-2 | Whether the answer avoids unsupported claims and stays within the provided reference answer. |
| `completeness` | 0-2 | Whether it includes the material conditions, deadlines, and procedures in the gold answer. |
| `source_recall` | 0.0-1.0 | Fraction of `gold_jo` IDs returned in the RAG sources. |

The summary reports the mean of each Judge score, mean total score out of 6,
mean source recall, and the five lowest-scoring cases. It labels every model
score as a Judge metric, not as a human-verified accuracy percentage.

## Runtime Contract

The full benchmark requires the existing RAG stack to be ready: Qdrant with
the corpus indexed, Ollama with the configured embedding and Qwen answer
models, and the allowlisted EXAONE Ollama Judge model. The current machine has no
reachable Ollama API, so only isolated unit tests are expected to run until
that runtime is provisioned.

Example command after the local runtime is ready:

```powershell
docker compose run --rm rag-api python scripts/evaluate_local_judge.py --judge-model exaone3.5:7.8b
```

## Error Handling

- Empty evaluation files or malformed JSONL rows stop before inference.
- An answer failure or invalid output is recorded as `answer_error`. A Judge
  model failure or invalid JSON is recorded as `judge_error`; it is never
  converted into a score and never discards the answer-side source metric.
- The summary separately counts answered cases, judged cases, answer errors,
  and Judge errors, so a partial run cannot be mistaken for a 76-case result.
- Completed case records are flushed before the next case starts, so an
  interrupted run retains its completed work.
- The runner exits non-zero when every case fails.
