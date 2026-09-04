# Evidence-Context RAG Design

> 상태 (2026-09-04): 미구현. parent(조) 확장 방식이 유지되었고, 이 설계는 `docs/superpowers/plans/2026-09-02-junior-rag-portfolio-readiness-roadmap.md`의 후속 과제로 넘긴다.

## Goal

Improve the internal-policy RAG answer path by passing budgeted paragraph-level evidence to Qwen, preserving evidence that would otherwise be removed by parent-article context trimming, and recording the exact stage that produces a fallback answer.

## Scope

This is the first improvement phase. It includes evidence-context construction, grounded-answer instructions, evaluation diagnostics, and regression tests. It does not add a cross-encoder reranker, a new embedding model, a cloud dependency, or a database outside Qdrant.

## Constraints

- Qwen remains the only RAG answer generator and receives system instructions separately from retrieved evidence and user input.
- Qwen answers only from selected internal-policy evidence and every successful answer retains source references.
- If selected evidence does not establish an answer, the response says that the document does not confirm it.
- Retrieved evidence and user questions remain untrusted data under the existing prompt-injection guard.
- The on-premise/local architecture remains intact: host Ollama, bge-m3 embeddings, Qdrant hybrid retrieval, and no Ollama container.
- Existing public RAG response fields, `answer` and `sources`, remain compatible.
- Diagnostic data is evaluation/development-only and is not exposed in the user-facing API response.
- Do not stage or commit files.

## Existing Evidence Available in Qdrant

Ingestion already embeds each paragraph (`child`) separately and stores these payload fields:

```text
chunk_id       jo-37-hang-2
parent_id      jo-37
text           the paragraph body
jo             제37조
hang_no        2
hang_label     적용 대상
parent_text    complete parent article (legacy context expansion only)
```

The new path uses `text` and the structural metadata. It does not use `parent_text` as the default Qwen context.

## Architecture

```text
natural-language question
  -> existing deterministic interpretation
  -> bge-m3 + BM25/RRF child search
  -> ranked child results
  -> evidence-context selector
       - preserve child-level ranking
       - de-duplicate exact child IDs
       - retain evidence that fits the character budget
       - skip an over-budget item and continue evaluating later candidates
  -> Qwen receives labelled evidence units
  -> answer + sources
```

The retrieval fetch remains over-fetched for recall. The selector, rather than parent expansion followed by tail deletion, determines what enters the Qwen prompt.

## Evidence Unit Contract

Introduce an internal immutable evidence value with at least:

```python
EvidenceUnit(
    chunk_id: str,
    parent_id: str,
    source_path: str,
    jo: str,
    hang_no: int | None,
    hang_label: str,
    score: float,
    text: str,
)
```

`EvidenceUnit` is built from a Qdrant child payload and is the unit used for prompt construction. Multiple selected evidence units from the same article may be selected, but duplicate child IDs must not be selected. The public `sources` contract remains article-level: each source has `chunk_id=parent_id`, `source_path`, and `score`, with duplicate parent IDs collapsed in first-selected order. Evaluation diagnostics retain the child-level evidence IDs.

## Budgeted Evidence Selection

The selector accepts ranked search results, requested answer top-k, and the existing prompt character budget.

1. Convert valid child payloads to evidence units in search-result order.
2. Remove duplicate `chunk_id` values.
3. Add an evidence unit if the resulting prompt remains within budget.
4. If the next unit would exceed budget, skip it and continue considering later units.
5. Stop after selecting the requested evidence top-k or exhausting candidates.
6. If no evidence unit can be selected, return the context-stage fallback.

This rule prevents a long high-ranked article from evicting a shorter lower-ranked evidence unit that directly answers the question. It intentionally does not add sibling expansion in this phase.

## Prompt and Grounding Contract

The Qwen system instructions must define selected evidence as the sole answer basis and require these behaviours:

- State the answer first, using only evidence facts.
- Include every material deadline, condition, exception, or procedure that appears in the evidence and changes the answer.
- Do not apply a rule from one labelled paragraph to a different policy or sub-program.
- When evidence defines applicability but does not define a separate procedure, clearly state that the separate procedure is not specified.
- Do not invent source labels or article numbers.

Prompt evidence uses labelled blocks such as:

```text
[evidence 1]
chunk_id: jo-37-hang-2
article: 제37조
paragraph: ② 적용 대상
content:
...
```

Public sources are generated from selected evidence metadata, not parsed from model-written article labels, and retain the existing article-level `chunk_id` format. The evaluation trace separately retains the selected child IDs.

## Fallback Diagnostics

Keep the existing public fallback answer text. Add an optional internal trace callback, parallel to the existing timing callback, with structured events for:

```text
search_result_count
selected_evidence_ids
prompt_char_count
fallback_stage = search | context | generation | null
generation_content_length
```

The answer export script consumes the trace callback and writes these fields into each JSONL record. Normal API and Streamlit responses do not expose them.

## Evaluation and Acceptance

Regression tests must prove:

- q13-style evidence at the tail of ranked candidates is selected when it fits after an oversized candidate is skipped.
- q45-style evidence survives ranking competition with a similar but wrong deadline article.
- selected evidence preserves child metadata in the evaluation trace, while the answer response preserves the existing parent-article source contract.
- a search fallback, context fallback, and blank-Qwen-generation fallback each emit distinct diagnostic stages.
- existing answer, source, CLI timing, ingestion, and API response contracts remain valid.

After implementation, run the existing 50-question set once to compare this phase against the baseline. Because its failures informed the design, treat it as a development comparison set. Create a separate natural-language holdout set before publishing any final resume metric.

## Non-Goals

- No cross-encoder reranker in this phase.
- No LLM query rewriting or natural-language-to-SQL.
- No hardcoded answers, question-ID rules, or article-number rules for evaluation questions.
- No automatic claim that accuracy has reached 99%.
