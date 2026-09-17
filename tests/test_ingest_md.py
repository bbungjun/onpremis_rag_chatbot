import importlib
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def ingest_module():
    try:
        return importlib.import_module("scripts.ingest_md")
    except ModuleNotFoundError as exc:
        pytest.fail(f"scripts.ingest_md should exist: {exc}")


def test_discover_markdown_files_recursively_returns_sorted_md_files(tmp_path):
    ingest = ingest_module()
    docs = tmp_path / "docs"
    (docs / "hr").mkdir(parents=True)
    (docs / "finance").mkdir(parents=True)
    (docs / "hr" / "leave-policy.md").write_text("# Leave\n", encoding="utf-8")
    (docs / "finance" / "expense.md").write_text("# Expense\n", encoding="utf-8")
    (docs / "ignore.txt").write_text("ignore", encoding="utf-8")

    files = ingest.discover_markdown_files(docs)

    assert files == [
        docs / "finance" / "expense.md",
        docs / "hr" / "leave-policy.md",
    ]


def _structure_chunks():
    """parent(조) 1개 + child(항) 2개로 구성된 새 청킹 출력 형태."""
    base_meta = {
        "pyeon": "제1편 총칙",
        "jang": "제1장 일반",
        "jeol": "제1절 통칙",
        "jo": "제1조",
        "jo_no": 1,
        "jo_title": "목적",
        "path": "제1편 총칙 > 제1장 일반 > 제1절 통칙 > 제1조",
    }
    parent = {
        "id": "jo-1",
        "type": "parent",
        "text": "제1조 (목적)\n전체 조문 본문",
        "metadata": dict(base_meta),
    }
    child1 = {
        "id": "jo-1-hang-1",
        "type": "child",
        "parent_id": "jo-1",
        "text": "첫째 항 본문",
        "metadata": {**base_meta, "hang_no": 1, "hang_label": "정의 및 목적"},
    }
    child2 = {
        "id": "jo-1-hang-2",
        "type": "child",
        "parent_id": "jo-1",
        "text": "둘째 항 본문",
        "metadata": {**base_meta, "hang_no": 2, "hang_label": "적용 대상"},
    }
    return parent, child1, child2


def test_ingest_directory_embeds_children_and_stores_structure_payload(
    tmp_path,
    monkeypatch,
    capsys,
):
    ingest = ingest_module()
    docs = tmp_path / "datasets" / "docs"
    docs.mkdir(parents=True)
    doc_path = docs / "regulations.md"
    doc_path.write_text("구조화 본문은 fake chunk_text 가 대체한다.\n", encoding="utf-8")

    settings = SimpleNamespace(
        ollama_base_url="http://ollama.test",
        embedding_model="bge-m3",
        qdrant_url="http://qdrant.test",
        qdrant_collection="chunks",
    )
    calls = {
        "chunk_text": [],
        "embed_text": [],
        "ensure_collection": [],
        "vectors": [],
    }
    parent, child1, child2 = _structure_chunks()

    def fake_chunk_text(text):
        calls["chunk_text"].append(text)
        return [parent, child1, child2]

    def fake_embed_text(base_url, model, text):
        calls["embed_text"].append((base_url, model, text))
        return [float(len(calls["embed_text"])), 0.2, 0.3]

    def fake_text_to_sparse(text):
        calls.setdefault("sparse", []).append(text)
        return {"indices": [len(text)], "values": [1.0]}

    monkeypatch.setattr(ingest, "chunk_text", fake_chunk_text)
    monkeypatch.setattr(ingest, "embed_text", fake_embed_text)
    monkeypatch.setattr(ingest, "text_to_sparse", fake_text_to_sparse)
    monkeypatch.setattr(
        ingest,
        "ensure_collection",
        lambda qdrant_url, collection_name, vector_size: calls["ensure_collection"].append(
            (qdrant_url, collection_name, vector_size)
        ),
    )
    monkeypatch.setattr(
        ingest,
        "upsert_chunk_vectors",
        lambda qdrant_url, collection_name, points: calls["vectors"].append(
            (qdrant_url, collection_name, points)
        ),
    )

    result = ingest.ingest_directory(docs, settings=settings)

    assert result == ingest.IngestionResult(
        documents_indexed=1,
        chunks_created=3,
        vectors_inserted=2,
    )
    # 파일 본문이 그대로 chunk_text(body) 로 전달된다.
    assert calls["chunk_text"] == ["구조화 본문은 fake chunk_text 가 대체한다.\n"]
    # 검색 단위인 child(항)만 임베딩한다 — parent(조)는 임베딩하지 않는다.
    assert calls["embed_text"] == [
        ("http://ollama.test", "bge-m3", "첫째 항 본문"),
        ("http://ollama.test", "bge-m3", "둘째 항 본문"),
    ]
    assert calls["ensure_collection"] == [("http://qdrant.test", "chunks", 3)]

    qdrant_points = calls["vectors"][0][2]
    assert len(qdrant_points) == 2

    first = qdrant_points[0]
    UUID(first["id"])
    # 포인트는 dense(bge-m3) + sparse(BM25) 두 벡터를 함께 싣는다.
    assert first["dense"] == [1.0, 0.2, 0.3]
    assert first["sparse"] == {"indices": [len("첫째 항 본문")], "values": [1.0]}
    payload = first["payload"]
    # 출처 표기에 필요한 필수 payload 필드. title 은 파일명, source_path 는 파일 경로.
    assert payload["source_path"].endswith("datasets/docs/regulations.md")
    assert payload["document_id"].endswith("datasets/docs/regulations.md")
    assert payload["title"] == "regulations.md"
    # 단일 문서이므로 chunk_id/parent_id 는 네임스페이스 없이 로컬 id 그대로다.
    assert payload["chunk_id"] == "jo-1-hang-1"
    assert payload["parent_id"] == "jo-1"
    # 구조 메타데이터 (편/장/절/조/항)
    assert payload["jang"] == "제1장 일반"
    assert payload["jo"] == "제1조"
    assert payload["jo_no"] == 1
    assert payload["path"] == "제1편 총칙 > 제1장 일반 > 제1절 통칙 > 제1조"
    assert payload["hang_no"] == 1
    assert payload["hang_label"] == "정의 및 목적"
    # 검색 단위 식별 + parent 확장용 denormalize
    assert payload["type"] == "child"
    assert payload["text"] == "첫째 항 본문"
    assert payload["parent_text"] == "제1조 (목적)\n전체 조문 본문"
    # 문서 메타데이터(doc_type/department 등)는 더 이상 저장하지 않는다.
    assert "department" not in payload
    assert "doc_type" not in payload

    # 두 child 의 chunk_id 는 유일하다.
    chunk_ids = [point["payload"]["chunk_id"] for point in qdrant_points]
    assert len(chunk_ids) == len(set(chunk_ids))

    output = capsys.readouterr().out
    assert "Documents indexed: 1" in output
    assert "Chunks created: 3" in output
    assert "Vectors inserted: 2" in output


def test_ingest_directory_reset_clears_qdrant_before_reindex(tmp_path, monkeypatch):
    ingest = ingest_module()
    docs = tmp_path / "datasets" / "docs"
    docs.mkdir(parents=True)
    (docs / "regulations.md").write_text("본문\n", encoding="utf-8")

    settings = SimpleNamespace(
        ollama_base_url="http://ollama.test",
        embedding_model="bge-m3",
        qdrant_url="http://qdrant.test",
        qdrant_collection="chunks",
    )
    events = []
    parent, child1, child2 = _structure_chunks()

    monkeypatch.setattr(ingest, "chunk_text", lambda text: [parent, child1, child2])
    monkeypatch.setattr(
        ingest,
        "embed_text",
        lambda base_url, model, text: events.append(("embed_text", text)) or [1.0, 0.2, 0.3],
    )
    monkeypatch.setattr(ingest, "text_to_sparse", lambda text: {"indices": [1], "values": [1.0]})
    monkeypatch.setattr(
        ingest,
        "delete_collection_if_exists",
        lambda qdrant_url, collection_name: events.append(
            ("delete_collection_if_exists", qdrant_url, collection_name)
        ),
    )
    monkeypatch.setattr(
        ingest,
        "ensure_collection",
        lambda qdrant_url, collection_name, vector_size: events.append(
            ("ensure_collection", qdrant_url, collection_name, vector_size)
        ),
    )
    monkeypatch.setattr(
        ingest,
        "upsert_chunk_vectors",
        lambda qdrant_url, collection_name, points: events.append(
            ("upsert_chunk_vectors", qdrant_url, collection_name, len(points))
        ),
    )

    result = ingest.ingest_directory(docs, settings=settings, reset=True)

    assert result == ingest.IngestionResult(
        documents_indexed=1,
        chunks_created=3,
        vectors_inserted=2,
    )
    assert ("delete_collection_if_exists", "http://qdrant.test", "chunks") in events
    assert ("ensure_collection", "http://qdrant.test", "chunks", 3) in events
    assert ("upsert_chunk_vectors", "http://qdrant.test", "chunks", 2) in events
    # 삭제 -> 컬렉션 보장 -> 업서트 순서
    assert events.index(
        ("delete_collection_if_exists", "http://qdrant.test", "chunks")
    ) < events.index(("ensure_collection", "http://qdrant.test", "chunks", 3))
    assert events.index(("ensure_collection", "http://qdrant.test", "chunks", 3)) < events.index(
        ("upsert_chunk_vectors", "http://qdrant.test", "chunks", 2)
    )


def test_ingest_cli_passes_reset_flag(monkeypatch):
    ingest = ingest_module()
    calls = []

    monkeypatch.setattr(
        ingest,
        "ingest_directory",
        lambda docs_path, reset=False, batch_size=128: calls.append((docs_path, reset, batch_size)),
    )

    assert ingest.main(["datasets/docs", "--reset"]) == 0
    assert calls == [("datasets/docs", True, 128)]


def test_repository_regulations_corpus_is_present_and_dense():
    ingest = ingest_module()
    docs_root = Path("datasets/docs")
    markdown_files = ingest.discover_markdown_files(docs_root)

    assert len(markdown_files) == 1
    assert markdown_files[0].name == "regulations.md"

    body = markdown_files[0].read_text(encoding="utf-8")

    # The corpus must stay dense enough to exercise chunking and retrieval.
    assert len(body.split()) >= 1000
    assert len(body) >= 1500

    required_policy_topics = {
        "연차": ("연차", "연차 유급휴가"),
        "재택근무": ("재택근무",),
        "출장비": ("출장", "출장비"),
        "경비 처리": ("경비", "증빙", "전표"),
        "온보딩": ("온보딩", "입사", "신규 입사"),
        "개인정보": ("개인정보",),
        "보안": ("보안", "VPN", "접근"),
    }
    missing_topics = [
        topic
        for topic, terms in required_policy_topics.items()
        if not any(term in body for term in terms)
    ]
    assert not missing_topics, f"Missing required policy topics: {missing_topics}"

    for marker in ("제1편", "제1장", "제1절", "제1조", "①"):
        assert marker in body
