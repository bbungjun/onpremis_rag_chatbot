# LLM Baseline Comparison Experiment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and run a reproducible first-pass experiment comparing Qwen, EXAONE, and Gemini 2.5 Flash under fixed RAG context and fixed generation settings.

**Architecture:** Keep ingestion, question interpretation, embedding, sparse search, Qdrant retrieval, parent expansion, system prompt, and user prompt construction identical for all models. For each question, build the RAG prompt once, save the retrieval metadata, then call Qwen, EXAONE, and Gemini with the same prompt and comparable generation settings. Store raw JSONL results plus a compact Markdown summary for manual review.

**Tech Stack:** Python, pytest, existing `app.rag_pipeline`, `app.question_interpreter`, `app.qwen_client`, `app.gemini_client`, Qdrant, Ollama, Vertex Gemini, Docker Compose.

---

## Experiment Decision

Use this as the 1st experiment baseline:

```text
temperature=0.2
num_predict/max_output_tokens=512
num_ctx=4096
retrieval_top_k=5
gemini_thinking_budget=0
repeat_count=3
```

Rationale:

```text
temperature=0.2 matches the current MVP default while keeping sampling variance low.
512 output tokens is large enough for policy answers but small enough for latency comparison.
retrieval_top_k=5 matches the current MVP default.
thinking_budget=0 keeps Gemini from receiving an extra reasoning budget that local models do not have.
repeat_count=3 exposes residual non-determinism without making the first run expensive.
```

The first experiment is not intended to find each model's best custom settings. It is intended to compare model behavior when the RAG evidence and generation budget are held constant.

## Evaluation Questions

Create a focused first-pass set with 12 questions:

```jsonl
{"id":"leave_deadline_01","question":"?곗감 ?좎껌? 硫곗튌 ?꾧퉴吏 ?댁빞 ?섎굹??","expected_source":["jo-39"],"answer_type":"answerable","must_include":["理쒖냼 3?곸뾽????,"?щ궡 洹쇳깭 ?쒖뒪??]}
{"id":"leave_general_01","question":"?곗감 ?좎껌 洹쒖젙??????뚮젮以?,"expected_source":["jo-39"],"answer_type":"answerable","must_include":["?곗감","3?곸뾽??]}
{"id":"leave_eligibility_01","question":"2???ㅼ뿉 ?곗감 ?좎껌?섎젮怨??섎뒗???좉퉴??","expected_source":["jo-39"],"answer_type":"answerable","must_include":["異⑹”?섏?","3?곸뾽??]}
{"id":"sick_leave_01","question":"蹂묎????대뼸寃??좎껌?댁빞 ?섎굹??","expected_source":["jo-41"],"answer_type":"answerable","must_include":["吏꾨떒??,"3?곸뾽??]}
{"id":"remote_work_01","question":"?ы깮洹쇰Т ?뱀씤 ?덉감???대뼸寃??섎굹??","expected_source":["jo-44"],"answer_type":"answerable","must_include":["?뱀씤"]}
{"id":"expense_evidence_01","question":"寃쎈퉬 泥섎━ ???대뼡 利앸튃???꾩슂?쒓???","expected_source":["jo-61"],"answer_type":"answerable","must_include":["利앸튃"]}
{"id":"corp_card_01","question":"踰뺤씤移대뱶 ?ъ슜 ???꾪몴 泥섎━???몄젣源뚯? ?댁빞 ?섎굹??","expected_source":["jo-62"],"answer_type":"answerable","must_include":["7?곸뾽??]}
{"id":"travel_settlement_01","question":"異쒖옣鍮??뺤궛? ?몄젣源뚯? ?댁빞 ?섎굹??","expected_source":["jo-64"],"answer_type":"answerable","must_include":["?뺤궛"]}
{"id":"privacy_doc_01","question":"媛쒖씤?뺣낫媛 ?ы븿??臾몄꽌???대뼸寃?蹂닿??댁빞 ?섎굹??","expected_source":["jo-75"],"answer_type":"answerable","must_include":["媛쒖씤?뺣낫"]}
{"id":"security_incident_01","question":"?뺣낫蹂댁븞 ?ш퀬媛 諛쒖깮?섎㈃ ?대뼸寃?蹂닿퀬?댁빞 ?섎굹??","expected_source":["jo-76"],"answer_type":"answerable","must_include":["蹂닿퀬"]}
{"id":"unsupported_01","question":"?щ궡 ?ъ뒪???댁슜 蹂댁“湲덉? ?쇰쭏?멸???","expected_source":[],"answer_type":"fallback","must_include":["臾몄꽌?먯꽌 ?뺤씤?섏? ?딆뒿?덈떎"]}
{"id":"unsupported_02","question":"諛섎젮?숇Ъ ?숇컲 異쒓렐 洹쒖젙? ?대뼸寃??섎굹??","expected_source":[],"answer_type":"fallback","must_include":["臾몄꽌?먯꽌 ?뺤씤?섏? ?딆뒿?덈떎"]}
```

If an expected `jo-*` does not exist in the current `datasets/docs/regulations.md`, replace that case with a question whose answer is confirmed by the current corpus before running the experiment.

## File Structure

```text
datasets/eval/model_comparison_v1.jsonl
  The curated first-pass question set.

scripts/run_model_comparison.py
  Builds one fixed RAG prompt per question and calls qwen3:4b-instruct,
  exaone3.5:7.8b, and gemini-2.5-flash with comparable settings.

tests/test_run_model_comparison.py
  Unit tests for question loading, fixed-context construction, model routing,
  result schema, and summary scoring helpers.

reports/model-comparison/
  Gitignored output directory for timestamped experiment results.
```

The experiment runner must not write API keys, credential paths, full environment variables, or secret values to result files.

---

### Task 1: Add the Evaluation Question Set

**Files:**
- Create: `datasets/eval/model_comparison_v1.jsonl`
- Test: `tests/test_run_model_comparison.py`

- [ ] **Step 1: Write the failing test for loading the question set**

Add this to `tests/test_run_model_comparison.py`:

```python
from __future__ import annotations

import json
from pathlib import Path


def test_model_comparison_question_set_has_required_fields():
    path = Path("datasets/eval/model_comparison_v1.jsonl")
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    assert len(rows) == 12
    ids = [row["id"] for row in rows]
    assert len(ids) == len(set(ids))
    for row in rows:
        assert isinstance(row["question"], str)
        assert row["question"].strip()
        assert row["answer_type"] in {"answerable", "fallback"}
        assert isinstance(row["expected_source"], list)
        assert isinstance(row["must_include"], list)
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```powershell
$env:COMPOSE_PROJECT_NAME='llmenhance'
docker compose run --rm rag-api pytest tests/test_run_model_comparison.py::test_model_comparison_question_set_has_required_fields -v
```

Expected:

```text
FAILED ... FileNotFoundError
```

- [ ] **Step 3: Create `datasets/eval/model_comparison_v1.jsonl`**

Create the file with the 12 JSONL rows listed in the "Evaluation Questions" section.

- [ ] **Step 4: Run the test to verify it passes**

Run:

```powershell
$env:COMPOSE_PROJECT_NAME='llmenhance'
docker compose run --rm rag-api pytest tests/test_run_model_comparison.py::test_model_comparison_question_set_has_required_fields -v
```

Expected:

```text
1 passed
```

---

### Task 2: Build a Fixed-Context Experiment Harness

**Files:**
- Create: `scripts/run_model_comparison.py`
- Modify: `tests/test_run_model_comparison.py`

- [ ] **Step 1: Write the failing test for fixed-context prompt construction**

Append this test:

```python
from types import SimpleNamespace


def test_build_fixed_context_uses_one_prompt_for_all_models(monkeypatch):
    import scripts.run_model_comparison as runner

    settings = SimpleNamespace(
        ollama_base_url="http://ollama.test",
        embedding_model="bge-m3",
        qdrant_url="http://qdrant.test",
        qdrant_collection="chunks",
        num_ctx=4096,
    )
    monkeypatch.setattr(runner, "embed_text", lambda *args: [0.1, 0.2, 0.3])
    monkeypatch.setattr(runner, "text_to_sparse", lambda text: {"indices": [1], "values": [1.0]})
    monkeypatch.setattr(
        runner,
        "search_chunks",
        lambda *args, **kwargs: [{"score": 1.0, "payload": {"chunk_id": "jo-39", "parent_id": "jo-39", "source_path": "datasets/docs/regulations.md", "title": "regulations.md", "jo": "??9議?, "path": "??9議?, "parent_text": "?곗감??理쒖냼 3?곸뾽???꾧퉴吏 ?좎껌?쒕떎."}}],
    )

    context = runner.build_fixed_context(
        question="?곗감 ?좎껌? 硫곗튌 ?꾧퉴吏 ?댁빞 ?섎굹??",
        settings=settings,
        top_k=5,
    )

    assert context.question_id == ""
    assert context.retrieval_question == "?곗감 ?좎껌? 硫곗튌 ?꾧퉴吏 ?댁빞 ?섎굹??"
    assert context.sources[0]["chunk_id"] == "jo-39"
    assert "[context]" in context.user_prompt
    assert "[canonical_question]" in context.user_prompt
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```powershell
$env:COMPOSE_PROJECT_NAME='llmenhance'
docker compose run --rm rag-api pytest tests/test_run_model_comparison.py::test_build_fixed_context_uses_one_prompt_for_all_models -v
```

Expected:

```text
FAILED ... ModuleNotFoundError: No module named 'scripts.run_model_comparison'
```

- [ ] **Step 3: Create the fixed-context data structure and builder**

Create `scripts/run_model_comparison.py` with:

```python
from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings
from app.embeddings import embed_text
from app.gemini_client import chat_gemini_vertex
from app.question_interpreter import interpret_question
from app.qwen_client import chat_qwen
from app.rag_pipeline import SYSTEM_PROMPT, _build_context, _prompt_char_budget, _search_top_k_for_parent_expansion
from app.sparse import text_to_sparse
from app.vector_store import search_chunks


LOCAL_MODELS = ("qwen3:4b-instruct", "exaone3.5:7.8b")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")


@dataclass(frozen=True)
class EvalQuestion:
    id: str
    question: str
    expected_source: list[str]
    answer_type: str
    must_include: list[str]


@dataclass(frozen=True)
class FixedContext:
    question_id: str
    question: str
    intent: str
    retrieval_question: str
    canonical_question: str
    user_prompt: str
    user_prompt_sha256: str
    sources: list[dict[str, Any]]


def load_questions(path: Path) -> list[EvalQuestion]:
    return [EvalQuestion(**json.loads(line)) for line in path.read_text(encoding="utf-8").splitlines()]


def build_fixed_context(
    question: str,
    settings: Settings,
    top_k: int,
    question_id: str = "",
) -> FixedContext:
    interpreted = interpret_question(question.strip())
    query_vector = embed_text(
        settings.ollama_base_url,
        settings.embedding_model,
        interpreted.retrieval_question,
    )
    query_sparse = text_to_sparse(interpreted.retrieval_question)
    search_results = search_chunks(
        settings.qdrant_url,
        settings.qdrant_collection,
        query_vector,
        query_sparse,
        _search_top_k_for_parent_expansion(top_k),
        metadata_filter=None,
    )
    parents, user_prompt = _build_context(
        interpreted,
        search_results,
        top_k,
        max_prompt_chars=_prompt_char_budget(settings.num_ctx),
    )
    sources = [
        {
            "source_path": parent.source_path,
            "chunk_id": parent.chunk_id,
            "score": parent.score,
        }
        for parent in parents
    ]
    return FixedContext(
        question_id=question_id,
        question=question,
        intent=interpreted.intent,
        retrieval_question=interpreted.retrieval_question,
        canonical_question=interpreted.canonical_question,
        user_prompt=user_prompt,
        user_prompt_sha256=hashlib.sha256(user_prompt.encode("utf-8")).hexdigest(),
        sources=sources,
    )
```

- [ ] **Step 4: Run the fixed-context test**

Run:

```powershell
$env:COMPOSE_PROJECT_NAME='llmenhance'
docker compose run --rm rag-api pytest tests/test_run_model_comparison.py::test_build_fixed_context_uses_one_prompt_for_all_models -v
```

Expected:

```text
1 passed
```

---

### Task 3: Add Model Invocation and Result Schema

**Files:**
- Modify: `scripts/run_model_comparison.py`
- Modify: `tests/test_run_model_comparison.py`

- [ ] **Step 1: Write the failing test for model routing**

Append:

```python
def test_run_one_model_routes_local_and_gemini_models(monkeypatch):
    import scripts.run_model_comparison as runner

    calls = []
    context = runner.FixedContext(
        question_id="leave_deadline_01",
        question="?곗감 ?좎껌? 硫곗튌 ?꾧퉴吏 ?댁빞 ?섎굹??",
        intent="deadline_lookup",
        retrieval_question="?곗감 ?좎껌? 硫곗튌 ?꾧퉴吏 ?댁빞 ?섎굹??",
        canonical_question="?곗감 ?좎껌? 硫곗튌 ?꾧퉴吏 ?댁빞 ?섎굹??",
        user_prompt="[context]\n?곗감??3?곸뾽?????좎껌\n\n[canonical_question]\n?곗감 ?좎껌? 硫곗튌 ?꾧퉴吏 ?댁빞 ?섎굹??",
        user_prompt_sha256="abc",
        sources=[{"source_path": "datasets/docs/regulations.md", "chunk_id": "jo-39", "score": 1.0}],
    )
    settings = SimpleNamespace(
        ollama_base_url="http://ollama.test",
        temperature=0.2,
        num_ctx=4096,
        num_predict=512,
    )

    def fake_chat_qwen(base_url, model, system_prompt, user_prompt, temperature, num_ctx, num_predict):
        calls.append(("ollama", model, temperature, num_predict))
        return f"{model} answer"

    def fake_chat_gemini_vertex(project, location, model, system_prompt, user_prompt, temperature, max_output_tokens, thinking_budget):
        calls.append(("gemini", model, temperature, max_output_tokens, thinking_budget))
        return f"{model} answer"

    monkeypatch.setattr(runner, "chat_qwen", fake_chat_qwen)
    monkeypatch.setattr(runner, "chat_gemini_vertex", fake_chat_gemini_vertex)

    qwen = runner.run_one_model(context, "qwen3:4b-instruct", settings, "project", "us-central1", "gemini-2.5-flash", 0)
    gemini = runner.run_one_model(context, "gemini-2.5-flash", settings, "project", "us-central1", "gemini-2.5-flash", 0)

    assert qwen["model"] == "qwen3:4b-instruct"
    assert gemini["model"] == "gemini-2.5-flash"
    assert calls == [
        ("ollama", "qwen3:4b-instruct", 0.2, 512),
        ("gemini", "gemini-2.5-flash", 0.2, 512, 0),
    ]
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```powershell
$env:COMPOSE_PROJECT_NAME='llmenhance'
docker compose run --rm rag-api pytest tests/test_run_model_comparison.py::test_run_one_model_routes_local_and_gemini_models -v
```

Expected:

```text
FAILED ... AttributeError: module 'scripts.run_model_comparison' has no attribute 'run_one_model'
```

- [ ] **Step 3: Implement model invocation**

Append to `scripts/run_model_comparison.py`:

```python
def run_one_model(
    context: FixedContext,
    model_name: str,
    settings: Settings,
    gemini_project: str,
    gemini_location: str,
    gemini_model: str,
    gemini_thinking_budget: int,
) -> dict[str, Any]:
    started = perf_counter()
    if model_name in LOCAL_MODELS:
        answer = chat_qwen(
            settings.ollama_base_url,
            model_name,
            SYSTEM_PROMPT,
            context.user_prompt,
            settings.temperature,
            settings.num_ctx,
            settings.num_predict,
        ).strip()
    elif model_name == gemini_model:
        answer = chat_gemini_vertex(
            gemini_project,
            gemini_location,
            gemini_model,
            SYSTEM_PROMPT,
            context.user_prompt,
            settings.temperature,
            settings.num_predict,
            gemini_thinking_budget,
        ).strip()
    else:
        raise ValueError(f"Unsupported model for experiment: {model_name}")

    return {
        "question_id": context.question_id,
        "question": context.question,
        "model": model_name,
        "answer": answer,
        "elapsed_ms": int((perf_counter() - started) * 1000),
        "sources": context.sources,
        "retrieval_question": context.retrieval_question,
        "canonical_question": context.canonical_question,
        "user_prompt_sha256": context.user_prompt_sha256,
        "answer_char_count": len(answer),
    }
```

- [ ] **Step 4: Run the routing test**

Run:

```powershell
$env:COMPOSE_PROJECT_NAME='llmenhance'
docker compose run --rm rag-api pytest tests/test_run_model_comparison.py::test_run_one_model_routes_local_and_gemini_models -v
```

Expected:

```text
1 passed
```

---

### Task 4: Add Automatic Scoring Helpers

**Files:**
- Modify: `scripts/run_model_comparison.py`
- Modify: `tests/test_run_model_comparison.py`

- [ ] **Step 1: Write the failing test for automatic scoring**

Append:

```python
def test_score_result_checks_expected_sources_and_required_phrases():
    import scripts.run_model_comparison as runner

    question = runner.EvalQuestion(
        id="leave_deadline_01",
        question="?곗감 ?좎껌? 硫곗튌 ?꾧퉴吏 ?댁빞 ?섎굹??",
        expected_source=["jo-39"],
        answer_type="answerable",
        must_include=["3?곸뾽??, "洹쇳깭 ?쒖뒪??],
    )
    result = {
        "answer": "?곗감??理쒖냼 3?곸뾽???꾧퉴吏 ?щ궡 洹쇳깭 ?쒖뒪?쒖쑝濡??좎껌?댁빞 ?⑸땲??",
        "sources": [{"chunk_id": "jo-39"}],
    }

    score = runner.score_result(question, result)

    assert score == {
        "expected_source_hit": True,
        "must_include_hit": True,
        "fallback_hit": False,
    }
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```powershell
$env:COMPOSE_PROJECT_NAME='llmenhance'
docker compose run --rm rag-api pytest tests/test_run_model_comparison.py::test_score_result_checks_expected_sources_and_required_phrases -v
```

Expected:

```text
FAILED ... AttributeError: module 'scripts.run_model_comparison' has no attribute 'score_result'
```

- [ ] **Step 3: Implement scoring helpers**

Append:

```python
def score_result(question: EvalQuestion, result: dict[str, Any]) -> dict[str, bool]:
    answer = str(result.get("answer", ""))
    source_ids = {str(source.get("chunk_id", "")) for source in result.get("sources", [])}
    expected = set(question.expected_source)
    return {
        "expected_source_hit": not expected or bool(expected & source_ids),
        "must_include_hit": all(phrase in answer for phrase in question.must_include),
        "fallback_hit": question.answer_type == "fallback"
        and "臾몄꽌?먯꽌 ?뺤씤?섏? ?딆뒿?덈떎" in answer,
    }
```

- [ ] **Step 4: Run the scoring test**

Run:

```powershell
$env:COMPOSE_PROJECT_NAME='llmenhance'
docker compose run --rm rag-api pytest tests/test_run_model_comparison.py::test_score_result_checks_expected_sources_and_required_phrases -v
```

Expected:

```text
1 passed
```

---

### Task 5: Add CLI Runner and Output Files

**Files:**
- Modify: `scripts/run_model_comparison.py`
- Modify: `tests/test_run_model_comparison.py`

- [ ] **Step 1: Write the failing test for output schema**

Append:

```python
def test_result_record_contains_experiment_metadata():
    import scripts.run_model_comparison as runner

    record = runner.build_result_record(
        experiment_id="20260622-150000",
        repeat_index=1,
        settings_snapshot={
            "temperature": 0.2,
            "num_predict": 512,
            "num_ctx": 4096,
            "retrieval_top_k": 5,
            "gemini_thinking_budget": 0,
        },
        question={"id": "leave_deadline_01"},
        model_result={"model": "qwen3:4b-instruct", "answer": "?듬?"},
        score={"expected_source_hit": True, "must_include_hit": True, "fallback_hit": False},
    )

    assert record["experiment_id"] == "20260622-150000"
    assert record["repeat_index"] == 1
    assert record["settings"]["temperature"] == 0.2
    assert record["question"]["id"] == "leave_deadline_01"
    assert record["result"]["model"] == "qwen3:4b-instruct"
    assert record["score"]["expected_source_hit"] is True
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```powershell
$env:COMPOSE_PROJECT_NAME='llmenhance'
docker compose run --rm rag-api pytest tests/test_run_model_comparison.py::test_result_record_contains_experiment_metadata -v
```

Expected:

```text
FAILED ... AttributeError: module 'scripts.run_model_comparison' has no attribute 'build_result_record'
```

- [ ] **Step 3: Implement output record and CLI**

Append:

```python
def build_result_record(
    *,
    experiment_id: str,
    repeat_index: int,
    settings_snapshot: dict[str, Any],
    question: dict[str, Any],
    model_result: dict[str, Any],
    score: dict[str, bool],
) -> dict[str, Any]:
    return {
        "experiment_id": experiment_id,
        "repeat_index": repeat_index,
        "settings": settings_snapshot,
        "question": question,
        "result": model_result,
        "score": score,
    }


def _default_project() -> str:
    return os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("GCP_PROJECT_ID", "")


def _settings_snapshot(settings: Settings, top_k: int, gemini_thinking_budget: int) -> dict[str, Any]:
    return {
        "temperature": settings.temperature,
        "num_predict": settings.num_predict,
        "num_ctx": settings.num_ctx,
        "retrieval_top_k": top_k,
        "gemini_thinking_budget": gemini_thinking_budget,
    }


def run_experiment(args: argparse.Namespace) -> Path:
    settings = Settings.from_env()
    questions = load_questions(Path(args.questions))
    experiment_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    output_dir = Path(args.output_dir) / experiment_id
    output_dir.mkdir(parents=True, exist_ok=True)
    result_path = output_dir / "results.jsonl"
    settings_snapshot = _settings_snapshot(settings, args.top_k, args.gemini_thinking_budget)
    models = [*LOCAL_MODELS, args.gemini_model]

    with result_path.open("w", encoding="utf-8") as handle:
        for repeat_index in range(1, args.repeat_count + 1):
            for question in questions:
                context = build_fixed_context(
                    question.question,
                    settings,
                    args.top_k,
                    question_id=question.id,
                )
                for model in models:
                    model_result = run_one_model(
                        context,
                        model,
                        settings,
                        args.gemini_project,
                        args.gemini_location,
                        args.gemini_model,
                        args.gemini_thinking_budget,
                    )
                    record = build_result_record(
                        experiment_id=experiment_id,
                        repeat_index=repeat_index,
                        settings_snapshot=settings_snapshot,
                        question=asdict(question),
                        model_result=model_result,
                        score=score_result(question, model_result),
                    )
                    handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    write_summary(result_path)
    return output_dir


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run baseline LLM comparison over fixed RAG contexts.")
    parser.add_argument("--questions", default="datasets/eval/model_comparison_v1.jsonl")
    parser.add_argument("--output-dir", default="reports/model-comparison")
    parser.add_argument("--repeat-count", type=int, default=3)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--gemini-project", default=_default_project())
    parser.add_argument("--gemini-location", default=os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1"))
    parser.add_argument("--gemini-model", default=GEMINI_MODEL)
    parser.add_argument("--gemini-thinking-budget", type=int, default=int(os.getenv("GEMINI_THINKING_BUDGET", "0")))
    args = parser.parse_args(argv)
    if not args.gemini_project:
        parser.error("--gemini-project is required unless GOOGLE_CLOUD_PROJECT or GCP_PROJECT_ID is set")
    output_dir = run_experiment(args)
    print(f"Experiment output: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the output schema test**

Run:

```powershell
$env:COMPOSE_PROJECT_NAME='llmenhance'
docker compose run --rm rag-api pytest tests/test_run_model_comparison.py::test_result_record_contains_experiment_metadata -v
```

Expected:

```text
1 passed
```

---

### Task 6: Add Markdown Summary

**Files:**
- Modify: `scripts/run_model_comparison.py`
- Modify: `tests/test_run_model_comparison.py`

- [ ] **Step 1: Write the failing test for summary generation**

Append:

```python
def test_write_summary_groups_by_model(tmp_path):
    import scripts.run_model_comparison as runner

    result_path = tmp_path / "results.jsonl"
    result_path.write_text(
        "\n".join(
            [
                json.dumps({"result": {"model": "qwen3:4b-instruct", "elapsed_ms": 1000}, "score": {"expected_source_hit": True, "must_include_hit": True, "fallback_hit": False}}, ensure_ascii=False),
                json.dumps({"result": {"model": "gemini-2.5-flash", "elapsed_ms": 500}, "score": {"expected_source_hit": True, "must_include_hit": False, "fallback_hit": False}}, ensure_ascii=False),
            ]
        ),
        encoding="utf-8",
    )

    summary_path = runner.write_summary(result_path)

    text = summary_path.read_text(encoding="utf-8")
    assert "| qwen3:4b-instruct |" in text
    assert "| gemini-2.5-flash |" in text
    assert "avg_elapsed_ms" in text
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```powershell
$env:COMPOSE_PROJECT_NAME='llmenhance'
docker compose run --rm rag-api pytest tests/test_run_model_comparison.py::test_write_summary_groups_by_model -v
```

Expected:

```text
FAILED ... AttributeError: module 'scripts.run_model_comparison' has no attribute 'write_summary'
```

- [ ] **Step 3: Implement summary generation**

Append:

```python
def write_summary(result_path: Path) -> Path:
    records = [
        json.loads(line)
        for line in result_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    by_model: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        model = record["result"]["model"]
        by_model.setdefault(model, []).append(record)

    lines = [
        "# Model Comparison Summary",
        "",
        "| model | runs | avg_elapsed_ms | source_hit_rate | must_include_rate | fallback_hit_rate |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for model, model_records in sorted(by_model.items()):
        elapsed = [item["result"]["elapsed_ms"] for item in model_records]
        source_hit = [item["score"]["expected_source_hit"] for item in model_records]
        must_include = [item["score"]["must_include_hit"] for item in model_records]
        fallback_hit = [item["score"]["fallback_hit"] for item in model_records]
        lines.append(
            "| "
            f"{model} | "
            f"{len(model_records)} | "
            f"{statistics.mean(elapsed):.1f} | "
            f"{sum(source_hit) / len(source_hit):.2f} | "
            f"{sum(must_include) / len(must_include):.2f} | "
            f"{sum(fallback_hit) / len(fallback_hit):.2f} |"
        )

    summary_path = result_path.with_name("summary.md")
    summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary_path
```

- [ ] **Step 4: Run the summary test**

Run:

```powershell
$env:COMPOSE_PROJECT_NAME='llmenhance'
docker compose run --rm rag-api pytest tests/test_run_model_comparison.py::test_write_summary_groups_by_model -v
```

Expected:

```text
1 passed
```

---

### Task 7: Run the First Experiment

**Files:**
- Read: `.env`
- Create output: a timestamped run directory such as `reports/model-comparison/20260622-150000/results.jsonl`
- Create output: a timestamped run directory such as `reports/model-comparison/20260622-150000/summary.md`

- [ ] **Step 1: Confirm fixed environment settings**

Run:

```powershell
Get-Content .env | Select-String -Pattern '^(TEAM_ENV_PROFILE|OLLAMA_BASE_URL|LLM_MODEL|GEMINI_MODEL|GEMINI_THINKING_BUDGET|RETRIEVAL_TOP_K|TEMPERATURE|NUM_CTX|NUM_PREDICT)='
```

Expected:

```text
TEAM_ENV_PROFILE=shared-ec2
OLLAMA_BASE_URL=http://YOUR_EC2_PUBLIC_IP:11434
LLM_MODEL=qwen3:4b-instruct
RETRIEVAL_TOP_K=5
TEMPERATURE=0.2
NUM_CTX=4096
NUM_PREDICT=512
GEMINI_MODEL=gemini-2.5-flash
GEMINI_THINKING_BUDGET=0
```

If `TEMPERATURE` differs from `0.2`, change it to `TEMPERATURE=0.2` for this baseline run, recreate containers, and keep the `.env` file uncommitted.

- [ ] **Step 2: Recreate services after `.env` changes**

Run:

```powershell
$env:COMPOSE_PROJECT_NAME='llmenhance'
docker compose up -d --force-recreate rag-api streamlit
```

Expected:

```text
Container llmenhance-rag-api-1 Started
Container llmenhance-streamlit-1 Started
```

- [ ] **Step 3: Confirm services are healthy**

Run:

```powershell
Invoke-RestMethod -Uri http://localhost:8000/health/services -TimeoutSec 10 | ConvertTo-Json -Depth 5
```

Expected:

```text
"api": {"status": "ok"}
"ollama": {"status": "ok"}
"qdrant": {"status": "ok"}
"gemini": {"status": "ok"}
```

- [ ] **Step 4: Run the experiment**

Run:

```powershell
$env:COMPOSE_PROJECT_NAME='llmenhance'
docker compose run --rm rag-api python scripts/run_model_comparison.py --repeat-count 3 --top-k 5
```

Expected:

```text
Experiment output: reports/model-comparison/20260622-150000
```

Expected result size:

```text
12 questions * 3 models * 3 repeats = 108 JSONL records
```

- [ ] **Step 5: Inspect summary**

Run:

```powershell
$latest = Get-ChildItem reports\model-comparison -Directory | Sort-Object Name | Select-Object -Last 1
Get-Content (Join-Path $latest.FullName 'summary.md')
```

Check:

```text
Each model has 36 runs.
source_hit_rate is comparable across models because context is fixed.
must_include_rate captures obvious answer misses.
avg_elapsed_ms reflects generation time plus model request overhead.
```

---

### Task 8: Manual Review and Decision

**Files:**
- Read: latest timestamped `reports/model-comparison/*/results.jsonl`
- Read: latest timestamped `reports/model-comparison/*/summary.md`

- [ ] **Step 1: Sample three failure records per model**

Run:

```powershell
@'
import json
from pathlib import Path

root = Path("reports/model-comparison")
result_path = sorted(root.iterdir())[-1] / "results.jsonl"
records = [json.loads(line) for line in result_path.read_text(encoding="utf-8").splitlines()]
for model in sorted({record["result"]["model"] for record in records}):
    failures = [
        record for record in records
        if record["result"]["model"] == model
        and not all(record["score"].values())
    ][:3]
    print("=" * 80)
    print(model)
    for record in failures:
        print(record["question"]["id"], record["question"]["question"])
        print(record["score"])
        print(record["result"]["answer"][:500])
        print()
'@ | docker compose run --rm rag-api python -
```

Expected:

```text
For each model, the output shows up to three concrete failure examples with score flags.
```

- [ ] **Step 2: Make the 1st experiment decision**

Record the decision in the thread:

```text
1李??ㅽ뿕 寃곕줎:
- 媛??鍮좊Ⅸ 紐⑤뜽:
- 媛???덉젙?곸쑝濡?洹쇨굅 議고빆???곕Ⅸ 紐⑤뜽:
- hallucination/fallback 臾몄젣媛 媛???곸? 紐⑤뜽:
- 2李??ㅽ뿕?먯꽌 ?쒕떇???꾨낫:
- ?뺢퇋??retrieval 媛쒖꽑???꾩슂??吏덈Ц ?좏삎:
```

Do not decide the production model using only `avg_elapsed_ms`. The production decision must consider source hit, required phrase hit, fallback correctness, and manual review examples.

---

## Verification Commands

Run these before calling the experiment implementation complete:

```powershell
$env:COMPOSE_PROJECT_NAME='llmenhance'
docker compose run --rm rag-api pytest tests/test_run_model_comparison.py -v
ruff check scripts/run_model_comparison.py tests/test_run_model_comparison.py
ruff format --check scripts/run_model_comparison.py tests/test_run_model_comparison.py
git diff --check
.\scripts\dev_verify.ps1
```

Expected:

```text
All pytest tests pass.
ruff check reports All checks passed.
ruff format reports files already formatted.
git diff --check exits 0.
dev_verify.ps1 prints SETUP_OK.
```

## Self-Review

Spec coverage:

```text
Covered: fixed generation settings, same retrieved context, Qwen/EXAONE/Gemini comparison, repeat count, source-based scoring, latency capture, output artifacts, and manual review.
```

Placeholder scan:

```text
Passed. The plan has no incomplete markers, vague implementation steps, or undefined follow-up steps.
```

Type consistency:

```text
EvalQuestion, FixedContext, build_fixed_context, run_one_model, score_result, build_result_record, write_summary, and run_experiment are defined before use in the plan. Test names and command targets match the functions introduced in the tasks.
```

Risk check:

```text
The plan intentionally isolates generation quality by reusing one fixed prompt per question. It does not measure retrieval variation between API calls. End-to-end UI behavior remains a separate smoke test after model-quality comparison.
```
