"""Diagnostic only: measure evidence delivery without generating a Qwen answer.

Rebuilds the synthetic Markdown corpus in Qdrant Local memory. It never writes
to the service's Qdrant collection. Raw outputs belong under ignored reports/.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import re
import subprocess
import sys
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
ARTICLE = re.compile(r"제\s*(\d+)\s*조(?:의\s*(\d+))?")
LAW_PREFIX = re.compile(r"(?:[가-힣]+법|시행령|시행규칙)\s*$")


def extract_links(parents: dict[str, str]) -> tuple[dict[str, list[str]], list[dict]]:
    """Extract explicit in-document references, not semantic/inferred edges."""
    links = {key: set() for key in parents}
    external = []
    for source, text in parents.items():
        for match in ARTICLE.finditer(text):
            target = f"jo-{match[1]}"
            if match[2]:
                target += f"-sub-{match[2]}"
            prefix = text[max(0, match.start() - 30) : match.start()]
            if LAW_PREFIX.search(prefix) or target not in parents:
                external.append({"source": source, "target": target})
            elif source != target:
                links[source].add(target)
    return {key: sorted(value) for key, value in links.items()}, external


def classify_missing(gold, candidates, parents, context) -> dict[str, list[str]]:
    """Assign each missing required article to its first failed stage."""
    return {
        "candidate_missing": sorted(set(gold) - set(candidates)),
        "parent_missing": sorted((set(gold) & set(candidates)) - set(parents)),
        "context_missing": sorted((set(gold) & set(parents)) - set(context)),
    }


def graph_distances(links, seeds, targets) -> dict[str, int | None]:
    """Directed reachability only; this is not a measured retrieval improvement."""
    distances = dict.fromkeys(seeds, 0)
    queue = deque(seeds)
    while queue:
        source = queue.popleft()
        for target in links.get(source, []):
            if target not in distances:
                distances[target] = distances[source] + 1
                queue.append(target)
    return {target: distances.get(target) for target in targets}


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _parent_id(hit) -> str:
    return hit["payload"]["parent_id"]


def main(argv=None) -> int:
    import httpx
    from dotenv import load_dotenv
    from qdrant_client import QdrantClient

    from app import vector_store
    from app.chunking import chunk_text
    from app.config import Settings
    from app.embeddings import embed_text
    from app.question_interpreter import interpret_question
    from app.rag_pipeline import _build_context, _expand_to_parents, _prompt_char_budget
    from app.sparse import text_to_sparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset", type=Path, default=ROOT / "datasets/eval/connection_diagnostic.jsonl"
    )
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--ollama-url", default="http://localhost:11434")
    args = parser.parse_args(argv)
    if not args.output.resolve().is_relative_to(ROOT / "reports/retrieval-eval"):
        parser.error("--output must be inside ignored reports/retrieval-eval")

    load_dotenv(ROOT / ".env", override=False)
    settings = Settings.from_env()
    top_k = settings.retrieval_top_k
    document = ROOT / "datasets/docs/regulations.md"
    body = document.read_text(encoding="utf-8")
    chunks = chunk_text(body)
    parents = {c["id"]: c["text"] for c in chunks if c["type"] == "parent"}
    children = [c for c in chunks if c["type"] == "child"]
    cases = [
        json.loads(line)
        for line in args.dataset.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if len({c["id"] for c in cases}) != len(cases):
        raise ValueError("duplicate case ID")
    for case in cases:
        if not case["gold_jo"] or set(case["gold_jo"]) - parents.keys():
            raise ValueError(f"invalid gold articles: {case['id']}")
        if set(case["gold_jo"]) != set(case["requirements"]):
            raise ValueError(f"missing evidence rationale: {case['id']}")
    links, external = extract_links(parents)
    args.output.mkdir(parents=True, exist_ok=False)
    _write(args.output / "frozen_cases.json", cases)
    _write(args.output / "links.json", {"internal": links, "external_or_unresolved": external})
    tags = httpx.get(args.ollama_url + "/api/tags", timeout=10).json()["models"]
    model = next(
        m for m in tags if m["name"].split(":")[0] == settings.embedding_model.split(":")[0]
    )
    metadata = {
        "started_at": datetime.now(UTC).isoformat(),
        "backend": "Qdrant Local :memory: rebuilt from current synthetic corpus",
        "git_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "corpus_raw_sha256": _hash(document),
        "corpus_lf_sha256": hashlib.sha256(body.encode()).hexdigest(),
        "dataset_sha256": _hash(args.dataset),
        "source_sha256": {
            p: _hash(ROOT / p)
            for p in [
                "app/rag_pipeline.py",
                "app/question_interpreter.py",
                "app/vector_store.py",
                "app/chunking.py",
                "app/sparse.py",
                "scripts/audit_retrieval_connections.py",
            ]
        },
        "embedding_model": model["name"],
        "embedding_digest": model["digest"],
        "qdrant_client": importlib.metadata.version("qdrant-client"),
        "kiwipiepy": importlib.metadata.version("kiwipiepy"),
        "ollama_version": httpx.get(args.ollama_url + "/api/version", timeout=10).json(),
        "top_k": top_k,
        "candidate_limit": top_k * 4,
        "num_ctx": settings.num_ctx,
        "prompt_char_budget": _prompt_char_budget(settings.num_ctx),
        "parents": len(parents),
        "children": len(children),
        "internal_directed_edges": sum(map(len, links.values())),
        "external_or_unresolved_references": external,
        "generation": "not called",
        "judge": "not called",
    }
    _write(args.output / "run.json", metadata)

    # Batch encoding changes ingestion transport only. Query encoding uses the
    # exact product embed_text function. This fresh index is not the live index.
    vectors = []
    for start in range(0, len(children), 16):
        response = httpx.post(
            args.ollama_url + "/api/embed",
            timeout=120,
            json={
                "model": settings.embedding_model,
                "input": [c["text"] for c in children[start : start + 16]],
                "truncate": False,
            },
        )
        response.raise_for_status()
        batch = response.json()["embeddings"]
        if len(batch) != len(children[start : start + 16]):
            raise ValueError("embedding batch size mismatch")
        vectors.extend(batch)
        print(f"Embedded {len(vectors)}/{len(children)}", flush=True)

    client = QdrantClient(":memory:")
    collection = "connection_diagnostic"
    with patch.object(vector_store, "QdrantClient", return_value=client):
        vector_store.ensure_collection("audit-local", collection, len(vectors[0]))
        points = []
        from uuid import NAMESPACE_URL, uuid5

        for chunk, dense in zip(children, vectors, strict=True):
            points.append(
                {
                    "id": str(uuid5(NAMESPACE_URL, chunk["id"])),
                    "dense": dense,
                    "sparse": text_to_sparse(chunk["text"]),
                    "payload": {
                        **chunk["metadata"],
                        "chunk_id": chunk["id"],
                        "parent_id": chunk["parent_id"],
                        "parent_text": parents[chunk["parent_id"]],
                        "document_id": "doc:datasets/docs/regulations.md",
                        "source_path": "datasets/docs/regulations.md",
                        "title": "regulations.md",
                        "type": "child",
                        "text": chunk["text"],
                    },
                }
            )
        vector_store.upsert_chunk_vectors("audit-local", collection, points)
        results = []
        for case in cases:
            interpreted = interpret_question(case["question"])
            dense = embed_text(
                args.ollama_url, settings.embedding_model, interpreted.retrieval_question
            )
            hits = vector_store.search_chunks(
                "audit-local",
                collection,
                dense,
                text_to_sparse(interpreted.retrieval_question),
                top_k * 4,
            )
            expanded = _expand_to_parents(hits, top_k)
            context, prompt = _build_context(
                interpreted, hits, top_k, max_prompt_chars=_prompt_char_budget(settings.num_ctx)
            )
            candidate_ids = list(dict.fromkeys(_parent_id(h) for h in hits))
            parent_ids = [p.chunk_id for p in expanded]
            context_ids = [p.chunk_id for p in context]
            missing = classify_missing(case["gold_jo"], candidate_ids, parent_ids, context_ids)
            row = {
                **case,
                "retrieval_question": interpreted.retrieval_question,
                "candidate_parent_ids": candidate_ids,
                "parent_ids": parent_ids,
                "context_ids": context_ids,
                "prompt_chars": len(prompt),
                "context_over_budget": len(prompt) > _prompt_char_budget(settings.num_ctx),
                **missing,
                "missing_graph_distance_from_context": graph_distances(
                    links, context_ids, sorted(set(case["gold_jo"]) - set(context_ids))
                ),
                "hits": [
                    {
                        "child_id": h["payload"]["chunk_id"],
                        "parent_id": _parent_id(h),
                        "score": h["score"],
                    }
                    for h in hits
                ],
            }
            results.append(row)
            with (args.output / "results.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            print(
                case["id"],
                "parents",
                parent_ids,
                "context",
                context_ids,
                "missing",
                missing,
                flush=True,
            )
    client.close()
    summary = {}
    for kind in ("multi", "control"):
        selected = [r for r in results if r["kind"] == kind]
        summary[kind] = {"n": len(selected)}
        for stage in ("candidate_parent_ids", "parent_ids", "context_ids"):
            summary[kind][stage + "_all_required"] = sum(
                set(r["gold_jo"]) <= set(r[stage]) for r in selected
            )
        for stage in ("candidate_missing", "parent_missing", "context_missing"):
            summary[kind][stage + "_cases"] = [r["id"] for r in selected if r[stage]]
    _write(args.output / "summary.json", summary)
    metadata["finished_at"] = datetime.now(UTC).isoformat()
    _write(args.output / "run.json", metadata)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
