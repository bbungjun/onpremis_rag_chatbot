# Resume RAG Evaluation Report Implementation Plan

> 상태 (2026-09-04): 산출물 HTML은 로컬 reports/ 에만 두고 추적하지 않는다. 최신 수치는 `docs/portfolio/2026-08-31-rrf-ablation-reranker-evaluation.md` 참고.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a single Korean HTML report that explains the measured local RAG work and provides resume-safe statements.

**Architecture:** A standalone HTML file embeds its own CSS and all narrative content. It presents evidence from the 76-record answer export and observed Docker/Ollama/Qdrant verification, without JavaScript, network calls, or runtime dependencies.

**Tech Stack:** HTML5, embedded CSS, PowerShell static-content verification.

## Global Constraints

- Use only observed Qwen3:4b, BGE-M3, Qdrant, top-k 5, and 76-case results.
- Call 92.1/100 a Codex-as-Judge score and call 92.1% expected-source recall.
- State that this is a single benchmark run, not a user study or general production-accuracy claim.
- Keep the UI simple and readable, with no JavaScript or external resources.
- Do not stage or commit files.

---

### Task 1: Create and verify the standalone report

**Files:**
- Create: `reports/resume-rag-evaluation-report.html`
- Verify: `reports/resume-rag-evaluation-report.html`

**Interfaces:**
- Consumes: `reports/local-judge/20260803-rag76-qwen3-4b/answers.jsonl` metrics and the design specification.
- Produces: a local browser-openable HTML report with no external dependencies.

- [x] **Step 1: Add the static HTML document**

Create semantic sections named `overview`, `architecture`, `timeline`,
`evaluation`, `failure-analysis`, `resume`, and `reproduction`. Embed CSS in a
`<style>` block and include the observed metric strings `76/76`, `90.8%`,
`92.1%`, and `14.57초`.

- [x] **Step 2: Verify the document is self-contained and contains evidence**

Run:

```powershell
$content = Get-Content -Raw -Encoding utf8 reports/resume-rag-evaluation-report.html
$required = '<!doctype html>', '76/76', '90.8%', '92.1%', '14.57초', 'Codex-as-Judge', '단일 실행'
$missing = $required | Where-Object { $content -notmatch [regex]::Escape($_) }
if ($missing) { throw "Missing required report text: $($missing -join ', ')" }
if ($content -match '<script|https?://') { throw 'Report must not require scripts or external network resources.' }
```

Expected: the command exits successfully with no missing content.

- [x] **Step 3: Review the rendered source structure**

Run:

```powershell
Select-String -Path reports/resume-rag-evaluation-report.html -Pattern '<section id="(overview|architecture|timeline|evaluation|failure-analysis|resume|reproduction)">' -AllMatches
```

Expected: seven matching report sections, one for each required topic.

- [x] **Step 4: Leave changes unstaged**

Run:

```powershell
git status --short reports/resume-rag-evaluation-report.html
```

Expected: `?? reports/resume-rag-evaluation-report.html`; do not run `git add` or `git commit`.
