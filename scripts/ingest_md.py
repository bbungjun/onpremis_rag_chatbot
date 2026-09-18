from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.chunking import chunk_text
from app.config import Settings
from app.document_reader import read_document
from app.embeddings import embed_text
from app.sparse import text_to_sparse
from app.vector_store import (
    delete_collection_if_exists,
    ensure_collection,
    upsert_chunk_vectors,
)


@dataclass(frozen=True)
class IngestionResult:
    documents_indexed: int
    chunks_created: int
    vectors_inserted: int


def discover_markdown_files(root_path: str | Path) -> list[Path]:
    root = Path(root_path)
    return sorted(path for path in root.rglob("*.md") if path.is_file())


def discover_source_files(root_path: str | Path) -> list[Path]:
    root = Path(root_path)
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in {".md", ".hwp", ".hwpx"}
    )


def ingest_directory(
    root_path: str | Path,
    settings: Settings | None = None,
    *,
    reset: bool = False,
    batch_size: int = 128,
) -> IngestionResult:
    if batch_size <= 0:
        raise ValueError("batch_size must be greater than zero")
    settings = settings or Settings.from_env()
    source_files = discover_source_files(root_path)
    if not source_files:
        raise ValueError(f"No Markdown, HWP, or HWPX documents found: {root_path}")

    documents_indexed = 0
    chunks_created = 0
    vectors_inserted = 0
    points: list[dict] = []
    collection_ready = False

    if reset:
        # 기존 컬렉션을 지우기 전에 모든 입력을 추출·청킹할 수 있는지 확인한다.
        for path in source_files:
            _require_structured_chunks(chunk_text(read_document(path)), path)
        delete_collection_if_exists(settings.qdrant_url, settings.qdrant_collection)

    def flush() -> None:
        nonlocal collection_ready
        if not points:
            return
        if not collection_ready:
            ensure_collection(
                settings.qdrant_url,
                settings.qdrant_collection,
                vector_size=len(points[0]["dense"]),
            )
            collection_ready = True
        upsert_chunk_vectors(settings.qdrant_url, settings.qdrant_collection, list(points))
        points.clear()

    for path in source_files:
        source_path = _source_path(path)
        document_id = _document_id(source_path)
        title = path.name
        body = read_document(path)
        chunks = chunk_text(body)
        _require_structured_chunks(chunks, path)
        documents_indexed += 1
        chunks_created += len(chunks)

        # parent(조) 전체 텍스트는 검색 대상이 아니라 child 확장용 lookup 이다.
        parent_text_by_id = {
            chunk["id"]: chunk["text"] for chunk in chunks if chunk["type"] == "parent"
        }

        # 검색 단위인 child(항)만 임베딩해 Qdrant 포인트로 만든다.
        for chunk in chunks:
            if chunk["type"] != "child":
                continue

            chunk_id = chunk["id"]
            parent_id = chunk.get("parent_id", chunk_id)
            parent_text = parent_text_by_id.get(parent_id, chunk["text"])

            dense = embed_text(settings.ollama_base_url, settings.embedding_model, chunk["text"])
            sparse = text_to_sparse(chunk["text"])
            payload = {
                **chunk["metadata"],
                "chunk_id": chunk_id,
                "document_id": document_id,
                "source_path": source_path,
                "title": title,
                "type": "child",
                "parent_id": parent_id,
                "text": chunk["text"],
                "parent_text": parent_text,
            }
            points.append(
                {
                    "id": str(uuid5(NAMESPACE_URL, f"{document_id}::{chunk_id}")),
                    "dense": dense,
                    "sparse": sparse,
                    "payload": payload,
                }
            )
            vectors_inserted += 1
            if len(points) >= batch_size:
                flush()

    flush()

    result = IngestionResult(
        documents_indexed=documents_indexed,
        chunks_created=chunks_created,
        vectors_inserted=vectors_inserted,
    )
    print_result(result)
    return result


def print_result(result: IngestionResult) -> None:
    print(f"Documents indexed: {result.documents_indexed}")
    print(f"Chunks created: {result.chunks_created}")
    print(f"Vectors inserted: {result.vectors_inserted}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Ingest Markdown, HWP 5.0, and HWPX regulations into the RAG vector store."
    )
    parser.add_argument("docs_path", help="Directory containing Markdown, HWP, or HWPX documents")
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete the existing Qdrant collection before indexing",
    )
    args = parser.parse_args(argv)

    ingest_directory(args.docs_path, reset=args.reset, batch_size=args.batch_size)
    return 0


def _source_path(path: str | Path) -> str:
    resolved = Path(path).resolve()
    try:
        return resolved.relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return resolved.as_posix()


def _document_id(source_path: str) -> str:
    return f"doc:{source_path}"


def _require_structured_chunks(chunks: list[dict], path: Path) -> None:
    types = {chunk.get("type") for chunk in chunks}
    if "parent" not in types or "child" not in types:
        raise ValueError(f"조/항 구조를 찾지 못했습니다: {path}")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
