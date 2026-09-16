import importlib
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_hwp_reader_preserves_regulation_structure(monkeypatch, tmp_path):
    reader = importlib.import_module("app.document_reader")
    source = tmp_path / "leave.hwp"
    source.write_bytes(b"fixture")
    extracted = (
        "# **1. 제1편 인사**\n\n"
        "## **1-1. 제1장 휴가**\n\n"
        "### **1-1-1. 제1절 연차**\n\n"
        "**제1조 (신청 기한)**\n\n"
        "① 연차 사용일 3영업일 전까지 신청한다.\n\n"
        "② 팀장이 승인한다.\n"
    )
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args, 0, extracted, "")

    monkeypatch.setattr(reader.subprocess, "run", fake_run)
    text = reader.read_document(source, hwp_cli="hwp-test")

    assert text.startswith("# 제1편 인사\n")
    assert "## 제1장 휴가\n" in text
    assert "### 제1절 연차\n" in text
    chunks = importlib.import_module("app.chunking").chunk_text(text)
    assert [chunk["type"] for chunk in chunks] == ["parent", "child", "child"]
    assert chunks[1]["metadata"]["path"] == (
        "제1편 인사 > 제1장 휴가 > 제1절 연차 > 제1조"
    )
    assert calls[0][0] == ["hwp-test", "cat", str(source), "--format", "markdown"]
    assert calls[0][1]["shell"] is False


def test_hwp_reader_rejects_unstructured_extraction(monkeypatch, tmp_path):
    reader = importlib.import_module("app.document_reader")
    source = tmp_path / "broken.hwp"
    source.write_bytes(b"fixture")
    monkeypatch.setattr(
        reader.subprocess,
        "run",
        lambda args, **kwargs: subprocess.CompletedProcess(args, 0, "문서 제목만 있음", ""),
    )
    with pytest.raises(ValueError, match="제.*조"):
        reader.read_document(source, hwp_cli="hwp-test")


def test_ingest_mixed_documents_uploads_bounded_batches(tmp_path, monkeypatch):
    ingest = importlib.import_module("scripts.ingest_md")
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "a.md").write_text("first", encoding="utf-8")
    (docs / "b.hwp").write_bytes(b"binary")
    monkeypatch.setattr(ingest, "read_document", lambda path: path.name)

    def fake_chunks(_text):
        parent = {"id": "jo-1", "type": "parent", "text": "제1조 전체", "metadata": {}}
        children = [
            {
                "id": f"jo-1-hang-{number}",
                "type": "child",
                "parent_id": "jo-1",
                "text": f"항 {number}",
                "metadata": {},
            }
            for number in range(1, 4)
        ]
        return [parent, *children]

    monkeypatch.setattr(ingest, "chunk_text", fake_chunks)
    monkeypatch.setattr(ingest, "embed_text", lambda *_: [0.1, 0.2])
    monkeypatch.setattr(ingest, "text_to_sparse", lambda *_: {"indices": [1], "values": [1.0]})
    monkeypatch.setattr(ingest, "ensure_collection", lambda *_, **__: None)
    batches = []
    monkeypatch.setattr(
        ingest,
        "upsert_chunk_vectors",
        lambda _url, _name, points: batches.append(list(points)),
    )
    settings = SimpleNamespace(
        ollama_base_url="http://ollama.test",
        embedding_model="bge-m3",
        qdrant_url="http://qdrant.test",
        qdrant_collection="chunks",
    )

    result = ingest.ingest_directory(docs, settings=settings, batch_size=2)

    assert result.documents_indexed == 2
    assert result.vectors_inserted == 6
    assert [len(batch) for batch in batches] == [2, 2, 2]
    assert {point["payload"]["source_path"] for batch in batches for point in batch} == {
        str((docs / "a.md").resolve()).replace("\\", "/"),
        str((docs / "b.hwp").resolve()).replace("\\", "/"),
    }
    assert len({point["id"] for batch in batches for point in batch}) == 6


def test_reset_preserves_existing_collection_if_hwp_cannot_be_parsed(tmp_path, monkeypatch):
    ingest = importlib.import_module("scripts.ingest_md")
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "broken.hwp").write_bytes(b"broken")

    def unreadable(_path):
        raise ValueError("제N조 없음")

    monkeypatch.setattr(ingest, "read_document", unreadable)
    deleted = []
    monkeypatch.setattr(ingest, "delete_collection_if_exists", lambda *_: deleted.append(True))
    settings = SimpleNamespace(qdrant_url="http://qdrant.test", qdrant_collection="chunks")

    with pytest.raises(ValueError, match="제N조"):
        ingest.ingest_directory(docs, settings=settings, reset=True)

    assert deleted == []


def test_reset_rejects_empty_input_before_deleting_collection(tmp_path, monkeypatch):
    ingest = importlib.import_module("scripts.ingest_md")
    deleted = []
    monkeypatch.setattr(ingest, "delete_collection_if_exists", lambda *_: deleted.append(True))
    settings = SimpleNamespace(qdrant_url="http://qdrant.test", qdrant_collection="chunks")

    with pytest.raises(ValueError, match="No Markdown or HWP"):
        ingest.ingest_directory(tmp_path, settings=settings, reset=True)

    assert deleted == []


def test_ingest_rejects_unstructured_markdown_instead_of_reporting_success(tmp_path):
    ingest = importlib.import_module("scripts.ingest_md")
    (tmp_path / "notes.md").write_text("조문이 없는 메모", encoding="utf-8")
    settings = SimpleNamespace(qdrant_url="http://qdrant.test", qdrant_collection="chunks")

    with pytest.raises(ValueError, match="조/항"):
        ingest.ingest_directory(tmp_path, settings=settings)


def test_synthetic_policy_generator_produces_distinct_scoped_rules():
    generator = importlib.import_module("scripts.generate_hwp_corpus")
    first = generator.make_policy(0)
    second = generator.make_policy(200)
    assert first.filename != second.filename
    assert first.markdown != second.markdown
    assert first.theme == second.theme
    assert first.role != second.role
    assert "합성 테스트 문서" in first.markdown
    assert first.markdown.count("**제") >= 5
    assert "①" in first.markdown


def test_real_hwp_fixture_roundtrip_preserves_articles_and_paragraphs():
    cli = os.environ.get("HWP_CLI_PATH") or shutil.which("hwp")
    if not cli:
        pytest.skip("HWP CLI is unavailable on this host")
    reader = importlib.import_module("app.document_reader")
    source = Path(__file__).parent / "fixtures" / "synthetic-policy-00001.hwp"
    text = reader.read_document(source, hwp_cli=cli)
    chunks = importlib.import_module("app.chunking").chunk_text(text)
    assert sum(chunk["type"] == "parent" for chunk in chunks) == 8
    assert sum(chunk["type"] == "child" for chunk in chunks) == 24
    assert "SYN-POL-00001" in text


def test_two_hwp_files_flow_through_ingestion_with_distinct_point_ids(
    tmp_path, monkeypatch
):
    cli = os.environ.get("HWP_CLI_PATH") or shutil.which("hwp")
    if not cli:
        pytest.skip("HWP CLI is unavailable on this host")
    ingest = importlib.import_module("scripts.ingest_md")
    docs = tmp_path / "docs"
    docs.mkdir()
    fixture = Path(__file__).parent / "fixtures" / "synthetic-policy-00001.hwp"
    shutil.copyfile(fixture, docs / "a.hwp")
    shutil.copyfile(fixture, docs / "b.hwp")
    monkeypatch.setenv("HWP_CLI_PATH", cli)
    monkeypatch.setattr(ingest, "embed_text", lambda *_: [0.1, 0.2])
    monkeypatch.setattr(ingest, "text_to_sparse", lambda *_: {"indices": [1], "values": [1.0]})
    monkeypatch.setattr(ingest, "ensure_collection", lambda *_, **__: None)
    uploaded = []
    monkeypatch.setattr(
        ingest,
        "upsert_chunk_vectors",
        lambda _url, _name, points: uploaded.extend(points),
    )
    settings = SimpleNamespace(
        ollama_base_url="http://ollama.test",
        embedding_model="bge-m3",
        qdrant_url="http://qdrant.test",
        qdrant_collection="chunks",
    )

    result = ingest.ingest_directory(docs, settings=settings, batch_size=7)

    assert (result.documents_indexed, result.chunks_created, result.vectors_inserted) == (
        2, 64, 48
    )
    assert len({point["id"] for point in uploaded}) == 48
    assert {point["payload"]["title"] for point in uploaded} == {"a.hwp", "b.hwp"}
