# Resume-oriented RAG Evaluation HTML Report Design

> 상태 (2026-09-04): 이 설계로 만든 HTML 보고서는 2026-08-03 76문항 기준이며 저장소에 추적하지 않는다. 채택된 최신 수치는 `docs/portfolio/2026-08-31-rrf-ablation-reranker-evaluation.md`를 따른다.

## Goal

Create one Korean HTML report that lets the project owner understand the actual
local RAG implementation and turn verified results into accurate resume and
interview statements.

## Audience and scope

- Primary reader: the project owner preparing a resume.
- The report is a static local artifact, not an application UI.
- It uses only observed repository configuration, execution logs, and the
  76-question Qwen3 evaluation run. It must not present unverified claims as
  measured facts.

## Content structure

1. Title and a short, plain-language project summary.
2. Four outcome cards: answer generation success, full-answer rate, expected
   source recall, and observed latency.
3. A concise architecture flow from Markdown policy documents to the answer
   with sources.
4. A chronological implementation and validation timeline: local Ollama
   availability, Qdrant/Docker startup, indexing, Qwen3 thinking-mode fix,
   export, and evaluation.
5. Evaluation-method section defining the 76 questions, top-k setting,
   Correct / Partial / Incorrect rubric, and the distinction between
   deterministic source recall and Codex-as-Judge scoring.
6. Results table, question-type comparison, and a transparent failure analysis.
7. Resume-ready statements and an interview explanation that scope claims to
   the stated benchmark.
8. Reproduction commands, changed-file summary, test result, and caveats.

## Visual approach

Use simple, accessible CSS only: a limited color palette, readable Korean
system fonts, bordered cards, tables with horizontal scrolling on small screens,
and no JavaScript or external dependencies. UI styling must aid scanning but
not obscure the technical evidence.

## Data integrity rules

- State the exact runtime: Qwen3:4b, BGE-M3, Qdrant, top-k 5, and 76 cases.
- Label the 92.1/100 answer-quality score as Codex-as-Judge, not a user study.
- Label 92.1% expected-source recall as matching the specified gold clause in
  retrieved sources.
- Include the five retrieval failures and the two partial-answer cases.
- Note that the benchmark is a single observed run; it does not establish
  general production accuracy.

## Validation

The deliverable must open as a standalone HTML file and contain no broken local
file links. Verify its key Korean text and metrics with a static content check.
