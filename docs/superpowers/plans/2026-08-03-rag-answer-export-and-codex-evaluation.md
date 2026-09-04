# RAG Answer Export and Codex Evaluation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist actual RAG-generated answers for the committed 76-case dataset so they can be evaluated by Codex against gold answers and returned source IDs.

**Architecture:** A dedicated runner will load the existing evaluation JSONL, invoke the existing RAG pipeline with injected answer generation for unit tests, and append a durable record for every case. It will not invoke a Judge model or alter production answer generation. Codex will consume the resulting records only after the RAG run completes.

**Tech Stack:** Python 3.11, existing `app.rag_pipeline`, JSONL, pytest, Docker Compose.

## Global Constraints

- Qwen remains the only RAG answer-generation model.
- Do not send policy documents, gold answers, or generated answers to an external API.
- Store generated answers only beneath Git-ignored `reports/local-judge/`.
- Append and flush each completed record before evaluating the next case.
- Do not commit generated reports, `.env`, or Docker volumes.

---

### Task 1: Add a durable RAG answer exporter

**Files:**

- Create: `scripts/export_rag_eval_answers.py`
- Create: `tests/test_export_rag_eval_answers.py`

**Interfaces:**

- Consumes: `EvalCase` and `load_cases()` from `scripts.evaluate_local_judge`, plus an injectable `answer(question, *, top_k)` callable.
- Produces: `run_export(cases, *, answer_model, top_k, output_dir, run_id, answer) -> Path`.

- [ ] **Step 1: Write failing persistence tests**

```python
def test_run_export_writes_real_answer_and_source_recall(tmp_path):
    output = exporter.run_export(
        [runner.EvalCase("q1", "일상어", "연차는?", ("jo-39",), "3영업일 전")],
        answer_model="qwen3:4b", top_k=5, output_dir=tmp_path, run_id="test",
        answer=lambda question, *, top_k: {
            "answer": "최소 3영업일 전 신청합니다.",
            "sources": [{"chunk_id": "doc:reg::jo-39"}],
        },
    )
    record = json.loads((output / "answers.jsonl").read_text(encoding="utf-8"))
    assert record["status"] == "answered"
    assert record["source_recall"] == 1.0
```

- [ ] **Step 2: Run the test and verify RED**

Run: `python -m pytest tests/test_export_rag_eval_answers.py -v`

Expected: FAIL because the exporter module does not exist.

- [ ] **Step 3: Implement minimal append-only export**

For each case, persist `case.id`, `case.type`, question, gold answer, `gold_jo`, generated answer, returned source IDs, deterministic source recall, and elapsed milliseconds. Record `answer_error` only for inference/response validation failures. Add `run.json` with timestamp, model name, `top_k`, case count, and dataset SHA-256.

- [ ] **Step 4: Run the exporter tests and verify GREEN**

Run: `python -m pytest tests/test_export_rag_eval_answers.py -v`

Expected: PASS.

### Task 2: Run the actual local RAG evaluation set

**Files:**

- Uses: `scripts/export_rag_eval_answers.py`
- Produces: Git-ignored `reports/local-judge/<run-id>/answers.jsonl`

- [ ] **Step 1: Verify the local stack**

Run: `docker compose ps`, `curl http://localhost:6333`, and `docker compose run --rm rag-api python -m app.healthcheck`.

- [ ] **Step 2: Rebuild vectors from the current policy corpus**

Run: `docker compose run --rm rag-api python scripts/ingest_md.py datasets/docs --reset`.

- [ ] **Step 3: Run all 76 cases**

Run: `docker compose run --rm rag-api python scripts/export_rag_eval_answers.py --top-k 5`.

- [ ] **Step 4: Check run completeness**

Verify exactly 76 `answered` or `answer_error` JSONL records and retain the summary even after interruption.

### Task 3: Codex Judge report

**Files:**

- Reads: generated `answers.jsonl` and `datasets/eval/qa_set.jsonl`
- Produces: a conversational report only; no report is presented as a human-labelled ground truth.

- [ ] **Step 1: Score each generated answer**

Use the fixed rubric: correctness, groundedness, and completeness on 0..2. Compare only the persisted candidate answer, gold answer, and actual returned source IDs.

- [ ] **Step 2: Report aggregate metrics**

Report means per rubric item, total score out of 6, source recall, failures, and representative error patterns. Clearly label the result as Codex-as-Judge rather than a human-verified accuracy rate.
