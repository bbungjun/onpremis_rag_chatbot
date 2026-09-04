# AGENTS.md

This file defines how AI agents and contributors should work inside the `llmenhance` repository.

## Project Identity

`llmenhance` is an MVP for an internal policy and company document chatbot.

The product is not a generic RAG demo. The target user is an employee asking practical company-policy questions, such as leave, remote work, travel reimbursement, expense processing, onboarding, privacy, and security rules.

## Non-Negotiable Product Rules

```text
1. Qwen is only for RAG answer generation.
2. Qwen must answer from retrieved internal document chunks.
3. If the retrieved context does not contain the answer, the chatbot must say that the document does not confirm it.
4. Every answer must include source references.
5. Superpowers, Codex, or other agent skills are development aids only; they are not part of the Qwen runtime.
6. The MVP must keep the on-premise/local story intact.
7. Qwen requests must keep system instructions separate from user/context data and include a prompt injection guard.
```

## MVP Architecture (current)

```text
Structured markdown regulations
-> structure-aware chunking (편/장/절/조/항, parent-child)
-> embedding (dense = bge-m3 via host Ollama; sparse = BM25-style kiwipiepy)
-> Qdrant hybrid search (dense + BM25, RRF fusion)
   + payload metadata filter (편/장/절/조/항 path, ...)
-> (optional) cross-encoder rerank
-> parent(조) expansion
-> qwen via Ollama
-> grounded answer with sources
```

## Expected User Questions

Use internal policy chatbot examples when writing docs, tests, and sample data:

```text
- 연차 신청은 며칠 전까지 해야 하나요?
- 재택근무 승인 절차는 어떻게 되나요?
- 출장비 정산은 언제까지 해야 하나요?
- 경비 처리 시 어떤 증빙이 필요한가요?
- 개인정보가 포함된 문서는 어떻게 보관해야 하나요?
```

Do not use project-meta questions such as:

```text
- RAG를 왜 쓰는 거야?
- 이 프로젝트에서 RAG를 쓰는 이유는?
```

Those questions describe the engineering project, not the chatbot product.

## Development Rules

```text
1. Prefer small modules with clear ownership.
2. Write tests before implementation for new behavior.
3. Do not reintroduce SQLite metadata filters in the MVP; if SQL is added later, use parameterized SQL.
4. Do not add natural-language-to-SQL in the MVP.
5. Do not put Ollama/Qwen inside Docker for the MVP; call host Ollama through host.docker.internal:11434.
6. Do not concatenate system prompts, retrieved context, and user questions into one undifferentiated prompt string.
7. Treat retrieved document chunks and user input as untrusted data in the Qwen system message.
8. Do not commit .env, cache directories, local DB files, or generated vector data.
```

## Portfolio Evidence Documentation

All implementation, experiment, evaluation, architecture, performance, and bug-fix work is
also portfolio evidence. Documentation is part of the definition of done, not an optional
summary added after coding.

For every material task, create or update a tracked document that records the complete
engineering narrative:

```text
1. Before / Problem
   - What user or system problem existed?
   - What observable failure, limitation, latency, accuracy, or maintenance cost proved it?
   - Include the reproduction, baseline, and affected scope when available.

2. Why / Analysis
   - What was the verified cause or design constraint?
   - Which alternatives were considered?
   - Why was the selected approach appropriate for this local/on-premise RAG product?

3. Solution / Implementation
   - What changed in the architecture, data flow, modules, interfaces, prompts, or tests?
   - Record the important decisions and trade-offs, not only a file list.

4. Verification
   - Record the exact tests, commands, manual scenarios, datasets, and runtime conditions used.
   - Distinguish automated tests, retrieval evaluation, LLM/Judge evaluation, and manual QA.

5. After / Measured Result
   - Record the observable result and compare it with the same-condition baseline.
   - Include quality, latency, resource, fallback, and source-grounding metrics when relevant.
   - State absolute percentage-point change and relative percentage change separately.

6. Evidence and Limitations
   - Link issues, design documents, result artifacts, commits, and PRs.
   - Record dataset size/hash, model, top-k, important settings, hardware, and execution date.
   - State what was not measured, remaining failures, threats to validity, and next experiments.
```

Use these documentation locations:

```text
Design and decision record before implementation:
  docs/superpowers/specs/<YYYY-MM-DD>-<topic>-design.md

Implementation plan when the change needs multiple coordinated steps:
  docs/superpowers/plans/<YYYY-MM-DD>-<topic>-implementation.md

Polished portfolio evidence after verification:
  docs/portfolio/<YYYY-MM-DD>-<topic>.md

Raw or sensitive local experiment output:
  reports/<experiment-name>/
```

The portfolio document must be readable without opening the code. It must explain the product
problem, the engineering reasoning, the implemented solution, and the measured outcome in a
Before -> Why -> After structure. Keep raw policy text, credentials, environment variables,
personal data, and other sensitive internal content out of tracked documentation.

Evidence rules:

```text
1. Never invent or estimate a metric that was not actually measured.
2. Do not compare results from different questions, datasets, models, hardware, or settings as
   a direct Before/After improvement unless the difference is explicitly controlled and stated.
3. Do not attribute the full RAG result to one component without an ablation or equivalent
   comparison. For example, an RRF result is not an RRF improvement without a dense/BM25 baseline.
4. Label development-set, held-out, single-run, Judge, and human-evaluation results accurately.
5. A passing pytest count is verification evidence, not a user-value or accuracy metric.
6. If runtime verification cannot be completed, document the blocker and write "not measured";
   do not produce a resume-ready outcome claim.
7. Preserve failing and partial cases in the record. Do not report only successful examples.
8. For a bug fix, the Before evidence is the failing reproduction/test and the After evidence is
   the same scenario passing after the smallest correct fix.
9. Update the portfolio document again when later measurements supersede an earlier result.
10. No material task is complete until its documentation reflects the final verified state.
```

## Subagent Work Rules

Subagents may work in parallel only when file ownership does not overlap.

Current ownership model:

```text
Chunking: app/chunking.py, tests/test_chunking.py
Ollama clients: app/embeddings.py, app/qwen_client.py, tests/test_ollama_clients.py
Sparse retrieval: app/sparse.py, tests/test_sparse.py
Qdrant store: app/vector_store.py, tests/test_vector_store.py
Ingestion: scripts/ingest_md.py, datasets/docs/regulations.md, tests/test_ingest_md.py
RAG query: app/rag_pipeline.py, scripts/ask_rag.py, scripts/ask_rag_gemini.py, tests/test_rag_pipeline.py, tests/test_ask_rag_gemini.py
```

If a task needs another owner's file, stop and report the dependency instead of editing it directly.

## Git Change Review and Publishing

Before committing or opening a PR, review the actual file-level changes instead of relying only on a summary.

Required workflow:

```text
1. Run git status --short --branch to confirm the working tree scope.
2. For each changed file, inspect git diff for that file and check that the change is intentional.
3. Run git diff --check to catch whitespace and conflict-marker issues.
4. If the diff is clean and relevant verification has passed, commit the intended files.
5. Push the branch and open a PR against origin/main, or update the existing PR for the branch.
6. In the final report, include the commit, PR link, and verification commands that passed or could not be run.
```

Do not stage unrelated files just to make the working tree clean.

## Verification Commands

Run these before claiming relevant work is complete:

```powershell
docker compose up -d
docker compose run --rm rag-api pytest -v
curl http://localhost:6333
docker compose run --rm rag-api python -m app.healthcheck
```
