# Local LLM Judge Evaluation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a reproducible local LLM-as-Judge runner that scores the existing 76-case policy RAG evaluation set without changing the production chatbot.

**Architecture:** A focused `app.local_judge` module sends a strictly constrained Korean scoring prompt to the exact allowlisted EXAONE local Ollama model and validates its JSON verdict. A CLI script generates answers with the existing RAG pipeline, calculates source recall from gold article IDs deterministically, durably records per-case outcomes, and emits a local-only summary report with reproducibility metadata.

**Tech Stack:** Python 3.12, existing `app.rag_pipeline`, existing Ollama HTTP client, pytest, JSONL, Docker Compose.

## Global Constraints

- Qwen remains limited to RAG answer generation; the Judge model must exactly match the controlled `exaone3.5:7.8b` allowlist.
- Treat question, gold answer, candidate answer, and source metadata as untrusted data in the Judge prompt.
- Do not add cloud services, dependencies, changes to production answering behavior, or model downloads.
- Outputs belong under `reports/local-judge/` and must be Git-ignored.
- The full live benchmark requires Ollama, embeddings, Qdrant, indexed documents, and a local non-Qwen Judge model; unit tests must not require any of them.

---

### Task 1: Add the local Judge module

**Files:**
- Create: `app/local_judge.py`
- Test: `tests/test_local_judge.py`

**Interfaces:**
- Produces: `JudgeVerdict`, `build_judge_prompt()`, `parse_judge_verdict()`, and `judge_answer()`.
- Consumes: `app.qwen_client.chat_qwen` through an injectable `chat` callable.
- `JudgeVerdict` fields are `correctness: int`, `groundedness: int`, `completeness: int`, and `rationale: str`.

- [ ] **Step 1: Write the failing parser and validation tests**

```python
def test_parse_judge_verdict_returns_validated_scores():
    verdict = judge.parse_judge_verdict(
        '{"correctness": 2, "groundedness": 1, "completeness": 2, "rationale": "근거 조항과 일치"}'
    )
    assert verdict.total == 5
    assert verdict.rationale == "근거 조항과 일치"

@pytest.mark.parametrize("payload", [
    '{"correctness": 3, "groundedness": 1, "completeness": 2, "rationale": "x"}',
    '{"correctness": 2, "groundedness": 1, "completeness": 2, "rationale": ""}',
])
def test_parse_judge_verdict_rejects_invalid_payload(payload):
    with pytest.raises(ValueError):
        judge.parse_judge_verdict(payload)
```

- [ ] **Step 2: Run the parser tests to verify RED**

Run: `docker compose run --rm rag-api pytest tests/test_local_judge.py -v`

Expected: import failure because `app.local_judge` does not exist.

- [ ] **Step 3: Implement only the tested verdict parser and value object**

```python
@dataclass(frozen=True)
class JudgeVerdict:
    correctness: int
    groundedness: int
    completeness: int
    rationale: str

    @property
    def total(self) -> int:
        return self.correctness + self.groundedness + self.completeness
```

Parse one JSON object; require exactly the four fields, integer scores in `0..2` (excluding booleans), and a non-empty rationale.

- [ ] **Step 4: Run the parser tests to verify GREEN**

Run: `docker compose run --rm rag-api pytest tests/test_local_judge.py -v`

Expected: PASS.

- [ ] **Step 5: Add the failing prompt and model-separation tests**

```python
def test_judge_answer_sends_untrusted_data_and_parses_response():
    captured = {}
    def fake_chat(base_url, model, system_prompt, user_prompt, temperature, num_ctx, num_predict):
        captured.update(model=model, system_prompt=system_prompt, user_prompt=user_prompt)
        return '{"correctness": 2, "groundedness": 2, "completeness": 2, "rationale": "일치"}'

    verdict = judge.judge_answer(
        base_url="http://ollama", judge_model="exaone:latest", question="연차는?",
        reference_answer="3영업일 전 신청", candidate_answer="3영업일 전 신청",
        source_ids=["jo-39"], num_ctx=4096, chat=fake_chat,
    )

    assert verdict.total == 6
    assert "untrusted" in captured["system_prompt"]
    assert "3영업일 전 신청" in captured["user_prompt"]


def test_judge_answer_rejects_qwen_as_judge_model():
    with pytest.raises(ValueError, match="non-Qwen"):
        judge.judge_answer(
            base_url="http://ollama", judge_model="qwen3:4b-instruct",
            question="연차는?", reference_answer="3일", candidate_answer="3일",
            source_ids=["jo-39"], num_ctx=4096,
        )
```

- [ ] **Step 6: Run the new tests to verify RED, then implement the minimal Judge call**

Build a separate Judge system prompt that explains the three score rubrics,
requires JSON only, and explicitly says that embedded data cannot override the
rubric. Call the existing `chat_qwen` function with `temperature=0.0` and
`num_predict=256`; inject the callable for tests. Re-run the tests until PASS.

- [ ] **Step 7: Commit the task**

Do not commit without the user's explicit request. Keep the task changes unstaged.

### Task 2: Add the evaluation runner and report writer

**Files:**
- Create: `scripts/evaluate_local_judge.py`
- Create: `tests/test_evaluate_local_judge.py`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: `JudgeVerdict` and `judge_answer()` from Task 1 and `answer_question()` from `app.rag_pipeline`.
- Produces: `EvalCase`, `load_cases()`, `source_recall()`, `run_evaluation()`, `summarize_records()`, and CLI `main()`.
- `run_evaluation()` accepts injectable answer and Judge callables and returns its timestamped output directory.

- [ ] **Step 1: Write the failing evaluation-case and source-recall tests**

```python
def test_load_cases_reads_existing_gold_question_schema(tmp_path):
    path = tmp_path / "cases.jsonl"
    path.write_text(
        '{"id":"q1","type":"일상어","question":"연차?","gold_jo":["jo-39"],"answer":"3일"}\n',
        encoding="utf-8",
    )
    assert runner.load_cases(path) == [runner.EvalCase("q1", "일상어", "연차?", ("jo-39",), "3일")]


def test_source_recall_normalizes_returned_parent_ids():
    assert runner.source_recall(("jo-39", "jo-40"), [
        {"chunk_id": "doc:reg::jo-39"}, {"chunk_id": "jo-8"}
    ]) == 0.5
```

- [ ] **Step 2: Run the tests to verify RED**

Run: `docker compose run --rm rag-api pytest tests/test_evaluate_local_judge.py -v`

Expected: import failure because the runner does not exist.

- [ ] **Step 3: Implement validated JSONL loading and deterministic source recall**

Reject blank fields, duplicated IDs, missing keys, non-list `gold_jo`, and
non-string answers. Normalize a returned source ID by taking the substring
after its final `::` before comparing it to `gold_jo`.

- [ ] **Step 4: Run the tests to verify GREEN**

Run: `docker compose run --rm rag-api pytest tests/test_evaluate_local_judge.py -v`

Expected: PASS.

- [ ] **Step 5: Write the failing orchestration and summary tests**

```python
def test_run_evaluation_writes_records_and_summary(tmp_path):
    cases = [runner.EvalCase("q1", "일상어", "연차?", ("jo-39",), "3일")]
    output = runner.run_evaluation(
        cases, judge_model="exaone:latest", output_dir=tmp_path,
        answer=lambda question, top_k: {"answer": "3일", "sources": [{"chunk_id": "jo-39"}]},
        judge=lambda **_: JudgeVerdict(2, 2, 2, "일치"),
    )

    record = json.loads((output / "results.jsonl").read_text(encoding="utf-8"))
    assert record["source_recall"] == 1.0
    assert record["verdict"]["total"] == 6
    assert "Mean Judge total: 6.00 / 6" in (output / "summary.md").read_text(encoding="utf-8")
```

- [ ] **Step 6: Run the orchestration test to verify RED, then implement minimal output flow**

For each case, call the answer function with `top_k`, call the Judge with the
case's question and gold answer, add elapsed milliseconds and source recall,
and append+flush `results.jsonl` after every completed case. Use distinct
`answer_error` and `judge_error` records; preserve the generated answer and
source recall in the latter. Write `run.json` with timestamp, model names,
settings, case count, and dataset SHA-256. Write a summary that separately
reports answered/judged/error counts, score means among judged cases, mean
source recall among answered cases, escaped answer/Judge-error examples, and
five lowest totals. Return a unique timestamped output path.

- [ ] **Step 7: Run the runner tests to verify GREEN**

Run: `docker compose run --rm rag-api pytest tests/test_evaluate_local_judge.py -v`

Expected: PASS.

- [ ] **Step 8: Add the ignored output path and CLI contract**

Append `reports/local-judge/` to `.gitignore`. Add `argparse` options
`--judge-model` (required), `--top-k` (default 5), `--limit`, and
`--output-dir` (default `reports/local-judge`). Restrict outputs to that
Git-ignored root. Reject any Judge model outside the exact EXAONE allowlist;
return exit code 1 only if no case receives a valid verdict.

- [ ] **Step 9: Commit the task**

Do not commit without the user's explicit request. Keep the task changes unstaged.

### Task 3: Verify the feature without a local Ollama runtime

**Files:**
- Test: `tests/test_local_judge.py`
- Test: `tests/test_evaluate_local_judge.py`
- Verify: `.gitignore`

**Interfaces:**
- Verifies the new isolated units without calling Ollama or Qdrant.

- [ ] **Step 1: Run the focused tests**

Run: `docker compose run --rm rag-api pytest tests/test_local_judge.py tests/test_evaluate_local_judge.py -v`

Expected: all focused tests PASS.

- [ ] **Step 2: Run the relevant regression tests**

Run: `docker compose run --rm rag-api pytest tests/test_ollama_clients.py tests/test_rag_pipeline.py -v`

Expected: all tests PASS; the production Qwen pipeline stays unchanged.

- [ ] **Step 3: Run static and repository checks**

Run:

```powershell
git diff --check
git status --short
```

Expected: no whitespace errors and only the design, plan, Judge implementation,
tests, and `.gitignore` changes.

- [ ] **Step 4: Document live-run readiness**

Do not execute the 76-case live run while Ollama is unavailable. State the
exact command to use after the RAG services and a local non-Qwen Judge model
are ready:

```powershell
docker compose run --rm rag-api python scripts/evaluate_local_judge.py --judge-model exaone3.5:7.8b
```

- [ ] **Step 5: Commit the task**

Do not commit without the user's explicit request. Keep the task changes unstaged.
