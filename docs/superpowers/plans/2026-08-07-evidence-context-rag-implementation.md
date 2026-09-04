# Evidence-Context RAG Implementation Plan

> 상태 (2026-09-04): 미구현. 코드 변경 없이 계획만 남아 있으며 후속 로드맵으로 대체한다.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (\`- [ ]\`) syntax for tracking.

**Goal:** Replace parent-article prompt expansion with budgeted child-evidence context, preserve compatible article-level sources, and record exact fallback stages in evaluation exports.

**Architecture:** Existing bge-m3 + BM25/RRF child search stays unchanged. \`app.rag_pipeline\` turns ranked child payloads into evidence units, selects units that fit the prompt budget without tail truncation, and sends labelled evidence to Qwen. Public sources stay article-level; an optional trace callback retains child evidence and fallback diagnostics for evaluation only.

**Tech Stack:** Python 3.11, Qdrant hybrid search, host Ollama with bge-m3 and Qwen, pytest, UTF-8 JSONL.

## Global Constraints

- Qwen is only the RAG answer generator; do not use it for query rewriting, reranking, judging, or SQL.
- Keep system instructions separate from user input and selected evidence, including the prompt-injection guard.
- Every successful public response retains the existing \`answer\` and article-level \`sources\` schema.
- Do not add a reranker, reindex the corpus, edit the 50-question dataset, add cloud dependencies, or hardcode question IDs or answers.
- Diagnostics are evaluation-only and must not be exposed from FastAPI or Streamlit.
- Preserve host Ollama through \`host.docker.internal:11434\` and local Qdrant.
- Do not stage, commit, push, or create a pull request.

---

## File Structure

| File | Responsibility |
|---|---|
| \`app/rag_pipeline.py\` | Evidence units, budget selection, labelled prompt, source projection, and trace events. |
| \`tests/test_rag_pipeline.py\` | Evidence, prompt, source, fallback, and trace contracts. |
| \`scripts/export_rag_eval_answers.py\` | Capture pipeline trace and write it into answer JSONL records. |
| \`tests/test_export_rag_eval_answers.py\` | Exporter diagnostic persistence and validation contracts. |

## Task 1: Build Budgeted Child-Evidence Context

**Files:**
- Modify: \`app/rag_pipeline.py:60-180, 216-376\`
- Modify: \`tests/test_rag_pipeline.py:38-480\`
- Test: \`tests/test_rag_pipeline.py\`

**Interfaces:**
- Consumes: Qdrant child payloads with \`chunk_id\`, \`parent_id\`, \`text\`, \`source_path\`, \`jo\`, \`hang_no\`, \`hang_label\`, and result \`score\`.
- Produces: \`EvidenceUnit\`, \`_select_evidence\`, labelled evidence prompts, and compatible parent-article sources.

- [ ] **Step 1: Add failing selector and source-projection tests**

Extend \`child_hit\` so each test can supply \`chunk_id\`, \`parent_id\`, \`text\`, \`jo\`, \`hang_no\`, and \`hang_label\`. Add these tests:

~~~python
def test_select_evidence_skips_oversized_candidate_and_keeps_later_fitting_evidence():
    pipeline = rag_pipeline()
    results = [
        child_hit(score=0.99, chunk_id="jo-13-hang-3", parent_id="jo-13", text="A" * 800),
        child_hit(score=0.90, chunk_id="jo-71-hang-3", parent_id="jo-71", text="B" * 800),
        child_hit(score=0.80, chunk_id="jo-14-hang-3", parent_id="jo-14", text="C" * 800),
        child_hit(score=0.70, chunk_id="jo-12-hang-3", parent_id="jo-12", text="정답 근거"),
    ]

    evidence = pipeline._select_evidence(
        pipeline.interpret_question("질문"), results, top_k=4, max_prompt_chars=2_200
    )

    assert [item.chunk_id for item in evidence] == [
        "jo-13-hang-3", "jo-71-hang-3", "jo-12-hang-3"
    ]
~~~

~~~python
def test_select_evidence_dedupes_child_ids_but_keeps_distinct_children_from_one_article():
    pipeline = rag_pipeline()
    results = [
        child_hit(score=0.95, chunk_id="jo-37-hang-2", parent_id="jo-37"),
        child_hit(score=0.94, chunk_id="jo-37-hang-2", parent_id="jo-37"),
        child_hit(score=0.90, chunk_id="jo-37-hang-3", parent_id="jo-37"),
    ]

    evidence = pipeline._select_evidence(
        pipeline.interpret_question("질문"), results, top_k=3, max_prompt_chars=2_000
    )

    assert [item.chunk_id for item in evidence] == ["jo-37-hang-2", "jo-37-hang-3"]
~~~

Add a ranking-competition test:

~~~python
def test_select_evidence_keeps_lower_ranked_receipt_deadline_evidence():
    pipeline = rag_pipeline()
    results = [
        child_hit(score=0.99, chunk_id="jo-82-hang-3", parent_id="jo-82", text="출장 종료일 5영업일 이내 정산"),
        child_hit(score=0.90, chunk_id="jo-70-hang-1", parent_id="jo-70", text="계약 검토 절차"),
        child_hit(score=0.80, chunk_id="jo-64-hang-2", parent_id="jo-64", text="거래일 7영업일 이내 영수증을 재무팀에 제출"),
    ]

    evidence = pipeline._select_evidence(
        pipeline.interpret_question("경비 영수증은 언제까지 제출해야 하나요?"),
        results,
        top_k=3,
        max_prompt_chars=2_000,
    )

    assert "jo-64-hang-2" in [item.chunk_id for item in evidence]
~~~

Add an integration-style test that captures Qwen input for two \`jo-37\` children and asserts the prompt contains \`chunk_id: jo-37-hang-2\` and \`paragraph: ② 적용 대상\`, while returned public sources contain only \`chunk_id: jo-37\`.

- [ ] **Step 2: Run selector tests to confirm RED**

Run:

~~~powershell
docker compose run --rm rag-api pytest -v tests/test_rag_pipeline.py -k "select_evidence or child_evidence"
~~~

Expected: FAIL because evidence selection and child-evidence prompt construction do not exist.

- [ ] **Step 3: Implement evidence conversion and budget-aware selection**

Add this immutable internal value in \`app/rag_pipeline.py\`:

~~~python
@dataclass(frozen=True)
class EvidenceUnit:
    chunk_id: str
    parent_id: str
    source_path: str
    jo: str
    hang_no: int | None
    hang_label: str
    score: float
    text: str
~~~

Implement \`_evidence_from_result(result) -> EvidenceUnit | None\`. It must require non-empty string \`chunk_id\`, \`source_path\`, and \`text\`; use non-empty \`parent_id\` when present and otherwise use a parent-form \`chunk_id\`; turn an integer \`hang_no\` into its value and all other values into \`None\`; convert an absent label to \`""\`.

Implement:

~~~python
def _select_evidence(
    interpreted_question: InterpretedQuestion,
    search_results: list[dict],
    *,
    top_k: int,
    max_prompt_chars: int,
) -> list[EvidenceUnit]:
    selected: list[EvidenceUnit] = []
    seen_chunk_ids: set[str] = set()
    for result in search_results:
        evidence = _evidence_from_result(result)
        if evidence is None or evidence.chunk_id in seen_chunk_ids:
            continue
        seen_chunk_ids.add(evidence.chunk_id)
        if len(selected) >= top_k:
            break
        candidate = [*selected, evidence]
        if len(_build_user_prompt(interpreted_question, candidate)) <= max_prompt_chars:
            selected.append(evidence)
    return selected
~~~

Use the existing over-fetch value. Replace \`_expand_to_parents\` in the answer path with this selector; do not read \`parent_text\` for Qwen context.

- [ ] **Step 4: Preserve article-level source compatibility**

Implement:

~~~python
def _sources_from_evidence(evidence: list[EvidenceUnit]) -> list[dict[str, object]]:
    sources: list[dict[str, object]] = []
    seen_parent_ids: set[str] = set()
    for item in evidence:
        if item.parent_id in seen_parent_ids:
            continue
        seen_parent_ids.add(item.parent_id)
        sources.append(
            {"source_path": item.source_path, "chunk_id": item.parent_id, "score": item.score}
        )
    return sources
~~~

Use this projection in the normal result. Update old tests that require a full parent article in the prompt, but retain their assertions for parent-article source ID, source path, score, and response shape.

- [ ] **Step 5: Replace parent prompt formatting and strengthen the answer contract**

Format evidence exactly as:

~~~text
[evidence {index}]
chunk_id: {chunk_id}
article: {jo}
paragraph: ② {hang_label}
content:
{text}
~~~

When \`hang_no is None\`, use \`paragraph: 미분류\`. Update \`SYSTEM_PROMPT\` to require material deadlines, conditions, exceptions, and procedures found in evidence; prohibit transferring a rule from one labelled paragraph to another; require “규정에 별도 절차가 명시돼 있지 않습니다” when a separate procedure is absent; and prohibit invented article labels.

- [ ] **Step 6: Run Task 1 tests to confirm GREEN**

Run:

~~~powershell
docker compose run --rm rag-api pytest -v tests/test_rag_pipeline.py
~~~

Expected: all pipeline tests pass with child evidence in the prompt and parent-level sources in the response.

- [ ] **Step 7: Inspect this task’s diff**

Run:

~~~powershell
git diff --check
git diff -- app/rag_pipeline.py tests/test_rag_pipeline.py
~~~

Do not stage or commit.

## Task 2: Add a Final Fallback Trace Event

**Files:**
- Modify: \`app/rag_pipeline.py:72-180\`
- Modify: \`tests/test_rag_pipeline.py:60-120, 507-552\`
- Test: \`tests/test_rag_pipeline.py\`

**Interfaces:**
- Consumes: optional \`trace: Callable[[dict[str, object]], None] | None\` in \`answer_question\`.
- Produces: exactly one final diagnostic mapping for each successful, search-fallback, context-fallback, or generation-fallback call.

- [ ] **Step 1: Add failing trace tests**

Add these four test cases: empty Qdrant results, unusable child payloads, a mocked blank Qwen response, and a grounded answer. Each captures \`traces = []\` and calls \`trace=traces.append\`.

The search-fallback test must assert this exact mapping:

~~~python
assert traces == [{
    "search_result_count": 0,
    "selected_evidence_ids": [],
    "prompt_char_count": 0,
    "fallback_stage": "search",
    "generation_content_length": 0,
}]
~~~

The context, generation, and success tests must respectively assert \`fallback_stage == "context"\`, \`"generation"\`, and \`None\`, and assert selected evidence IDs are child IDs when selection succeeds.

- [ ] **Step 2: Run trace tests to confirm RED**

Run:

~~~powershell
docker compose run --rm rag-api pytest -v tests/test_rag_pipeline.py -k traces
~~~

Expected: FAIL because \`answer_question\` has no \`trace\` keyword argument.

- [ ] **Step 3: Implement one callback event per pipeline call**

Add:

~~~python
TraceCallback = Callable[[dict[str, object]], None]

def answer_question(..., trace: TraceCallback | None = None) -> dict[str, Any]:
    ...
~~~

Track \`search_result_count\`, \`selected_evidence_ids\`, \`prompt_char_count\`, \`fallback_stage\`, and \`generation_content_length\` in local variables. Add \`_emit_trace(trace, ...)\` and invoke it exactly once immediately before every normal return. The callback must be a no-op when \`trace is None\`. Do not add diagnostics to the public result, log user text, or alter progress/timing event order.

- [ ] **Step 4: Run trace and full pipeline tests**

Run:

~~~powershell
docker compose run --rm rag-api pytest -v tests/test_rag_pipeline.py -k "traces or fallback or timing or progress"
docker compose run --rm rag-api pytest -v tests/test_rag_pipeline.py
~~~

Expected: all focused and full pipeline tests pass.

- [ ] **Step 5: Inspect this task’s diff**

Run:

~~~powershell
git diff --check
git diff -- app/rag_pipeline.py tests/test_rag_pipeline.py
~~~

Do not stage or commit.

## Task 3: Persist Diagnostics in Answer Exports

**Files:**
- Modify: \`scripts/export_rag_eval_answers.py:26-100, 208-219\`
- Modify: \`tests/test_export_rag_eval_answers.py:10-230\`
- Test: \`tests/test_export_rag_eval_answers.py\`

**Interfaces:**
- Consumes: \`answer(question, *, top_k, trace)\` and the pipeline’s final trace mapping.
- Produces: every answer-export record with a \`diagnostics\` object or \`null\`, while keeping current answer, source, recall, status, and elapsed-time fields.

- [ ] **Step 1: Add failing export-diagnostic tests**

Update existing fake answer callbacks to accept \`trace=None\`. Add:

~~~python
def test_run_export_writes_pipeline_diagnostics(tmp_path):
    case = runner.EvalCase("q1", "일상어", "질문", ("jo-1",), "정답")

    def answer(question, *, top_k, trace=None):
        assert trace is not None
        trace({
            "search_result_count": 4,
            "selected_evidence_ids": ["jo-1-hang-3"],
            "prompt_char_count": 321,
            "fallback_stage": None,
            "generation_content_length": 12,
        })
        return {"answer": "정답", "sources": [{"chunk_id": "jo-1"}]}

    output = exporter.run_export(
        [case], answer_model="qwen3:4b", top_k=5,
        output_dir=tmp_path, run_id="diagnostics", answer=answer,
    )

    record = json.loads((output / "answers.jsonl").read_text(encoding="utf-8"))
    assert record["diagnostics"]["selected_evidence_ids"] == ["jo-1-hang-3"]
~~~

Add an answer-error test that raises before trace emission and asserts \`record["diagnostics"] is None\`.

- [ ] **Step 2: Run exporter tests to confirm RED**

Run:

~~~powershell
docker compose run --rm rag-api pytest -v tests/test_export_rag_eval_answers.py
~~~

Expected: FAIL because \`run_export\` does not pass or persist a trace callback.

- [ ] **Step 3: Capture and validate the final trace**

Change \`AnswerCallable\` so \`trace: Callable[[dict[str, object]], None] | None = None\` is accepted. In \`_export_case\`, capture one trace mapping and pass its callback to \`answer\`.

Add a private diagnostic validator that accepts exactly:

~~~text
search_result_count
selected_evidence_ids
prompt_char_count
fallback_stage
generation_content_length
~~~

Require non-negative integer counts, a list of string child IDs, and \`fallback_stage\` of \`search\`, \`context\`, \`generation\`, or \`None\`. Write \`"diagnostics": diagnostics\` for both answered and answer-error records. In \`main\`, forward the received exporter trace callback to \`answer_question(..., trace=trace)\`. Do not add CLI flags or change report-root validation.

- [ ] **Step 4: Run export and evaluator regression tests**

Run:

~~~powershell
docker compose run --rm rag-api pytest -v tests/test_export_rag_eval_answers.py tests/test_evaluate_local_judge.py
~~~

Expected: all export records preserve existing fields and include validated diagnostics; evaluator parsing remains compatible.

- [ ] **Step 5: Inspect this task’s diff**

Run:

~~~powershell
git diff --check
git diff -- scripts/export_rag_eval_answers.py tests/test_export_rag_eval_answers.py
~~~

Do not stage or commit.

## Task 4: Verify Runtime Behaviour and Re-evaluate

**Files:**
- Verify: \`app/rag_pipeline.py\`
- Verify: \`scripts/export_rag_eval_answers.py\`
- Verify: generated ignored files in \`reports/local-judge/\`

**Interfaces:**
- Consumes: completed evidence context code, local Qdrant, host Ollama, and the 50 natural-language development cases.
- Produces: a fresh 50-case export with diagnostics and a baseline comparison; it does not claim a final held-out metric.

- [ ] **Step 1: Start and health-check services**

Run:

~~~powershell
docker compose up -d
(Invoke-WebRequest -UseBasicParsing http://localhost:6333).StatusCode
docker compose run --rm rag-api python -m app.healthcheck
~~~

Expected: HTTP 200 and configured Qwen, bge-m3, Qdrant URL, collection, and top-k in health-check output.

- [ ] **Step 2: Run all automated tests**

Run:

~~~powershell
docker compose run --rm rag-api pytest -v
~~~

Expected: all feature-relevant tests pass. Record, but do not alter, any unrelated existing failures.

- [ ] **Step 3: Export a fresh 50-question answer run**

Run:

~~~powershell
docker compose run --rm rag-api python scripts/export_rag_eval_answers.py --top-k 5 --output-dir reports/local-judge --run-id 20260807-evidence-context-natural50
~~~

Expected: \`reports/local-judge/20260807-evidence-context-natural50/answers.jsonl\` contains 50 answered records and a \`diagnostics\` field on every record.

- [ ] **Step 4: Inspect fallback attribution before any score claim**

Run:

~~~powershell
$records = Get-Content -Encoding utf8 reports/local-judge/20260807-evidence-context-natural50/answers.jsonl | ForEach-Object { $_ | ConvertFrom-Json }
$records | Group-Object { $_.diagnostics.fallback_stage } | Select-Object Name, Count
$records | Where-Object { $_.diagnostics.fallback_stage } | Select-Object @{n='id';e={$_.case.id}}, @{n='stage';e={$_.diagnostics.fallback_stage}}, @{n='evidence';e={$_.diagnostics.selected_evidence_ids -join ', '}}
~~~

Compare source recall, strict answer review, and latency with \`reports/local-judge/20260805-natural50-qwen3-4b/answers.jsonl\`. Label this 50-case set as development comparison data because it informed the design.

- [ ] **Step 5: Final diff and scope review**

Run:

~~~powershell
git status --short --branch
git diff --check
git diff -- app/rag_pipeline.py scripts/export_rag_eval_answers.py tests/test_rag_pipeline.py tests/test_export_rag_eval_answers.py
~~~

Report intentional files, commands that passed, unrelated existing failures, and measured runtime results. Do not stage, commit, push, or open a pull request.
