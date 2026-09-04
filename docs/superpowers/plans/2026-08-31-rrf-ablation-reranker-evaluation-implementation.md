# RRF Ablation and Local Reranker Evaluation Implementation Plan

> Design: `docs/superpowers/specs/2026-08-31-rrf-ablation-reranker-evaluation-design.md`
> Issue: <https://github.com/bbungjun/onpremis_rag_chatbot/issues/1>

## Baseline

- Focused regression suite: 112 passed
- Qdrant client: 1.18.0
- Native fusion support: RRF, weighted RRF, DBSF
- Existing production default: dense + BM25 RRF
- Development dataset: 50 natural-language policy questions
- Existing uncommitted work must be preserved.

## Step 1: Retrieval ranking metrics

**Files**

- Create `app/retrieval_metrics.py`
- Create `tests/test_retrieval_metrics.py`

**TDD sequence**

1. Add failing tests for single-gold and multi-gold Recall@1/3/5.
2. Add failing tests for Hit@k, MRR@5, and binary nDCG@5.
3. Add failing deterministic paired-bootstrap test.
4. Implement immutable metric values and the minimum calculation functions.
5. Run the focused tests and Ruff diagnostics.

## Step 2: Explicit Qdrant search strategies

**Files**

- Create `app/retrieval_search.py`
- Create `tests/test_retrieval_search.py`
- Preserve `app/vector_store.py` default behavior

**TDD sequence**

1. Add failing query-construction tests for dense, BM25, RRF, weighted RRF, and DBSF.
2. Add failing tests for identical candidate limits and returned result shape.
3. Add failing parent-collapse tests that preserve first-ranked child order.
4. Implement the explicit strategy API around Qdrant Query API.
5. Verify the existing vector-store tests still pass unchanged.

## Step 3: Evaluation runner and report contract

**Files**

- Create `app/retrieval_evaluation.py`
- Create `app/retrieval_reports.py`
- Create `scripts/evaluate_retrieval.py`
- Create `tests/test_retrieval_evaluation.py`
- Create `tests/test_retrieval_reports.py`
- Update `.gitignore`

**TDD sequence**

1. Add failing tests for one record per case/method and partial-failure persistence.
2. Add failing tests for run metadata, hashes, method settings, and secret exclusion.
3. Add failing tests for JSONL and Markdown summaries, including paired differences.
4. Implement quality execution with shared dense/sparse representations.
5. Implement warm latency repetitions with seeded method ordering.
6. Add CLI arguments from the design and safe report-root validation.

## Step 4: Local reranker adapter

**Files**

- Create `app/reranker.py`
- Create `tests/test_reranker.py`
- Create `requirements-reranker.txt`

**TDD sequence**

1. Add failing tests proving only query and child text reach the backend.
2. Add failing ordering and parent-collapse integration tests.
3. Implement lazy optional import and immutable runtime metadata.
4. Keep the dependency out of the default runtime path.
5. Verify cold-start and warm inference metadata on the actual local runtime.

## Step 5: End-to-end retrieval injection

**Files**

- Add the smallest explicit search dependency seam to `app/rag_pipeline.py`
- Update `scripts/export_rag_eval_answers.py`
- Update focused tests

**TDD sequence**

1. Add a failing pipeline test showing a selected search strategy controls returned sources.
2. Add a failing exporter test showing the method is recorded and forwarded.
3. Extract existing oversized pipeline responsibilities before adding the seam if needed.
4. Preserve the default RRF response and prompt/source contracts.
5. Run all RAG and export regressions.

## Step 6: Held-out dataset contract

**Files**

- Create `datasets/eval/qa_holdout.jsonl`
- Create or update dataset-integrity tests

**TDD sequence**

1. Add a failing test requiring 50 unique natural-language questions.
2. Reject article-number lookup wording and duplicate development questions.
3. Verify every gold parent exists in `regulations.md`.
4. Add 50 new answerable practical-policy questions.
5. Freeze and report the dataset SHA-256 before the final experiment.

## Step 7: Runtime experiments

1. Start Docker, Qdrant, and host Ollama.
2. Reindex the current regulation corpus.
3. Run all unit and integration tests.
4. Run development retrieval comparison for dense, BM25, RRF, weighted RRF, DBSF.
5. Tune weights and choose reranker candidate limit on development data only.
6. Run the local reranker comparison.
7. Freeze all settings.
8. Run the held-out retrieval comparison once.
9. Run Qwen end-to-end evaluation for dense, RRF, and the selected best method.

## Step 8: Portfolio evidence and final audit

**Files**

- Create `docs/portfolio/2026-08-31-rrf-ablation-reranker-evaluation.md`

Record Before, Why, implementation, verification commands, development results, held-out
results, latency trade-offs, failures, runtime conditions, hashes, limitations, and the exact
resume-safe statement. Do not claim an improvement whose paired held-out evidence is absent.

## Verification gates

```powershell
docker compose up -d
docker compose run --rm rag-api pytest -v
docker compose run --rm rag-api ruff check app scripts tests
curl http://localhost:6333
docker compose run --rm rag-api python -m app.healthcheck
git diff --check
```

Manual QA must run the retrieval CLI through its real command surface, inspect generated
`run.json`, `results.jsonl`, and `summary.md`, and ask at least one policy question through the
selected end-to-end path while confirming parent-level sources.
