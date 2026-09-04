# Local Setup

This guide defines the reproducible local development path for `llmenhance`.

The project keeps the MVP local/on-premise story intact:

```text
Docker Compose: rag-api + Qdrant
Windows host: Ollama + Qwen + bge-m3
Repository data: Markdown policy docs
Generated local state: Qdrant vectors + Docker volumes
```

## Agent Setup Contract

If you are a CLI coding agent asked to set up this project, follow this contract:

```text
1. Read README.md first.
2. Follow the Agent Setup Quickstart section exactly.
3. Do not move Ollama/Qwen into Docker.
4. Do not commit .env, storage/, local DB files, or vector data.
5. Report success only when scripts/dev_verify.ps1 prints SETUP_OK.
```

## Prerequisites

Install these on the Windows host before running setup:

```text
Docker Desktop
Ollama
Git
PowerShell
```

Ollama must run on the host, not inside Docker. The container reaches it through:

```text
http://host.docker.internal:11434
```

## One-Command Setup Path

From the repository root:

```powershell
.\scripts\dev_setup.ps1
.\scripts\dev_verify.ps1
```

`dev_setup.ps1` does the local bootstrap:

```text
- checks Docker and Ollama
- creates .env from .env.example when missing
- pulls bge-m3
- pulls qwen3:4b-instruct
- builds and starts Docker services
- rebuilds the Qdrant index from datasets/docs
```

`dev_verify.ps1` proves the setup:

```text
- checks Qdrant at localhost:6333
- runs app.healthcheck
- runs pytest
- asks a sample corporate-card policy question
- requires non-empty Sources
- prints SETUP_OK only after all checks pass
```

## Manual Equivalent

The setup script is intentionally simple. Its manual equivalent is:

```powershell
Copy-Item .env.example .env

ollama pull bge-m3
ollama pull qwen3:4b-instruct

docker compose up -d --build
docker compose run --rm rag-api python scripts/ingest_md.py datasets/docs --reset
```

Then verify:

```powershell
curl.exe http://localhost:6333
docker compose run --rm rag-api python -m app.healthcheck
docker compose run --rm rag-api pytest -v
docker compose run --rm rag-api python scripts/ask_rag.py "법인카드 사용 후 전표 처리는 언제까지 해야 하나요?" --top-k 3 --timing
```

## Troubleshooting

If Docker fails:

```text
Start Docker Desktop and rerun scripts/dev_setup.ps1.
```

If Ollama fails:

```text
Start Ollama on the Windows host and rerun scripts/dev_setup.ps1.
```

If Qdrant data looks stale:

```powershell
docker compose run --rm rag-api python scripts/ingest_md.py datasets/docs --reset
```

If a generated local file appears in Git status, do not commit it. Local RAG state belongs in:

```text
storage/
*.sqlite
*.sqlite3
Docker volumes
```

## Configuration Reference

Default `.env.example`:

```env
OLLAMA_BASE_URL=http://host.docker.internal:11434
LLM_MODEL=qwen3:4b
EMBEDDING_MODEL=bge-m3

QDRANT_URL=http://qdrant:6333
QDRANT_COLLECTION=llmenhance_chunks

RETRIEVAL_TOP_K=5
TEMPERATURE=0.2
NUM_CTX=4096
NUM_PREDICT=512
```

Override at run time with `-e`, for example `-e NUM_PREDICT=192 -e NUM_CTX=2048`.

`bge-m3` is the retrieval embedding model, not an answer model. Removing it breaks ingestion and
question embedding. For qwen3-family models the client sends `think: true` so reasoning is returned
in a separate field and the `content` field holds only the final answer.

## CLI QA

```powershell
docker compose run --rm rag-api python scripts/ask_rag.py "연차 신청은 며칠 전까지 해야 하나요?" --top-k 5 --timing
docker compose run --rm rag-api python scripts/ask_rag.py "출장비 정산은 언제까지 해야 하나요?" --top-k 5 --timing
```

Narrow the search with `--filter KEY=VALUE` (repeatable) only when you want to restrict to a
chapter or article; the question text is not parsed for structure.

```powershell
docker compose run --rm rag-api python scripts/ask_rag.py "휴가 신청 절차" --filter "jang=제2장 인사 관리" --top-k 5
```

`--timing` prints per-stage latency:

```text
Embedding question   bge-m3 dense embedding of the question (sparse tokenisation runs here too)
Qdrant search        dense + BM25 hybrid search and RRF fusion
Parent expansion     map child hits to parent articles, dedupe, build context from parent_text
Qwen generation      final LLM generation (the usual bottleneck)
```

## Verifying Sources

`Sources` is the list of parent articles the pipeline actually retrieved, not text written by the LLM.
To inspect a cited article, read its payload from Qdrant:

```powershell
@'
from qdrant_client import QdrantClient, models
from app.config import Settings

settings = Settings.from_env()
client = QdrantClient(url=settings.qdrant_url)
points, _ = client.scroll(
    collection_name=settings.qdrant_collection,
    scroll_filter=models.Filter(
        must=[models.FieldCondition(key="parent_id", match=models.MatchValue(value="jo-39"))]
    ),
    limit=1,
    with_payload=True,
)
payload = points[0].payload
print(payload["source_path"], payload["title"], payload["path"])
print(payload["parent_text"])
'@ | docker compose run --rm -T rag-api python -
```

To see the exact `[context]` prompt sent to the LLM:

```powershell
@'
from app.config import Settings
from app.embeddings import embed_text
from app.sparse import text_to_sparse
from app.vector_store import search_chunks
from app.rag_pipeline import _build_context

question = "연차 신청은 며칠 전까지 해야 하나요?"
settings = Settings.from_env()
dense = embed_text(settings.ollama_base_url, settings.embedding_model, question)
sparse = text_to_sparse(question)
results = search_chunks(settings.qdrant_url, settings.qdrant_collection, dense, sparse, 5)
parents, user_prompt = _build_context(question, results, 5)
print(user_prompt)
'@ | docker compose run --rm -T rag-api python -
```

## Gemini Comparison Path (experimental)

Same retrieval, generation swapped to Vertex Gemini. Requires Google ADC on the host.

```powershell
gcloud auth application-default login
gcloud config set project YOUR_GCP_PROJECT

docker compose run --rm `
  -e GOOGLE_CLOUD_PROJECT=YOUR_GCP_PROJECT `
  -e GOOGLE_CLOUD_LOCATION=us-central1 `
  -e GOOGLE_APPLICATION_CREDENTIALS=/tmp/gcloud_adc.json `
  -v "$env:APPDATA\gcloud\application_default_credentials.json:/tmp/gcloud_adc.json:ro" `
  rag-api python scripts/ask_rag_gemini.py "법인카드 사용 후 전표 처리는 언제까지 해야 하나요?" --top-k 5 --max-output-tokens 256 --timing
```

Defaults: `gemini-2.5-flash`, `thinking_budget=0`. With thinking enabled, short
`max_output_tokens` can truncate the answer; use `--thinking-budget -1` only for experiments.
Never commit the ADC file; mount it read-only.

## Presentation Split Chat Frontend

Side-by-side view: local Ollama + Qwen RAG on the left, AWS Bedrock RAG on the right. Stored demo
results work without AWS credentials; the live-run button needs AWS credentials and `BEDROCK_MODEL_ID`.

```powershell
docker compose run --rm -p 8787:8787 rag-api python scripts/presentation_frontend.py --host 0.0.0.0 --port 8787
```

Open `http://localhost:8787`.

## More Troubleshooting

Ollama connection refused (`host.docker.internal:11434`): make sure Ollama runs on the Windows host,
`OLLAMA_BASE_URL` in `.env` points to it, then restart Docker Desktop if needed.

Slow Qwen answers: check `--timing`; reduce `NUM_PREDICT` (192–256), `NUM_CTX` (2048), or `--top-k` (3),
or use a smaller model.

Disk space: `ollama list`, then `ollama rm <model>` for unused answer models. Keep `bge-m3`.
Unload from memory with `ollama stop <model>`.

Qdrant looks inconsistent: re-ingest with `--reset`. As a last resort:

```powershell
docker compose down -v
docker compose up -d
docker compose run --rm rag-api python scripts/ingest_md.py datasets/docs --reset
```

`rag-api` fails to bind port 8000: another container or process already uses it. Tests and CLI still
work through `docker compose run`.

## Never Commit

```text
.env, .env.backup.*
storage/, *.sqlite, Docker volumes, Qdrant data
Ollama model files
Google credential / ADC files
reports/retrieval-eval/, reports/local-judge/ (raw evaluation output)
```
