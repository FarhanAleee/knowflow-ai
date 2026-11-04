import hashlib
import math
import os
from pathlib import Path

import fitz
import pytest

from app.services.embedding_service import DEFAULT_MODEL_NAME
from app.services.retrieval_pipeline import RetrievalPipeline


class MockEmbeddingService:
    model_name = DEFAULT_MODEL_NAME

    @staticmethod
    def _vector_from_text(text: str) -> list[float]:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        vector = [0.0] * 384
        for index in range(384):
            value = (digest[index % len(digest)] + index * 13) % 101
            vector[index] = ((value / 50.0) - 1.0) * 0.75
        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0:
            return [1.0] + [0.0] * 383
        return [value / norm for value in vector]

    def embed(self, items):
        if not items:
            return []
        first_item = items[0]
        if isinstance(first_item, str):
            return [self._vector_from_text(item) for item in items]
        return [self._vector_from_text(item.text) for item in items]


def make_text_file(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def make_pdf_file(path: Path, text: str) -> Path:
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), text, fontsize=12)
    document.save(path)
    document.close()
    return path


def _make_pipeline(tmp_path: Path):
    embedding_service = MockEmbeddingService()
    persist_directory = tmp_path / "chroma"
    vector_store = __import__("app.services.vector_store", fromlist=["ChromaVectorStore"]).ChromaVectorStore(
        persist_directory=persist_directory,
        embedding_service=embedding_service,
    )
    return RetrievalPipeline(embedding_service=embedding_service, vector_store=vector_store)


def test_index_document_and_retrieve_relevant_chunks(tmp_path):
    document_path = make_text_file(
        tmp_path / "policy.txt",
        "The annual climate policy review covers emissions reductions and long-term resilience. "
        "Teams must track carbon budgets and prepare for flooding risks.",
    )
    pipeline = _make_pipeline(tmp_path)

    result = pipeline.index_document(document_path)

    assert result.status == "success"
    assert result.chunks_indexed > 0
    assert pipeline.vector_store.count() == result.chunks_indexed

    hits = pipeline.retrieve("climate policy emissions reductions", top_k=3)
    assert hits
    assert hits[0].metadata["source_filename"] == "policy.txt"
    assert "climate" in hits[0].text.lower()


def test_reindexing_same_document_is_idempotent_and_persistence_survives(tmp_path):
    document_path = make_text_file(tmp_path / "repeat.txt", "Alpha beta gamma delta. Alpha beta gamma delta.")
    pipeline = _make_pipeline(tmp_path)

    first = pipeline.index_document(document_path)
    first_count = pipeline.vector_store.count()
    first_ids = [item.chunk_id for item in pipeline.vector_store.get_chunks(source_filename="repeat.txt")]

    second = pipeline.index_document(document_path)
    second_ids = [item.chunk_id for item in pipeline.vector_store.get_chunks(source_filename="repeat.txt")]

    assert first.status == "success"
    assert second.status == "success"
    assert pipeline.vector_store.count() == first_count
    assert first_ids == second_ids

    reopened = _make_pipeline(tmp_path)
    assert reopened.vector_store.count() == first_count
    assert reopened.vector_store.get_chunks(source_filename="repeat.txt")


def test_changed_document_replaces_old_chunks_without_stale_ids(tmp_path):
    document_path = tmp_path / "changing.txt"
    make_text_file(document_path, "Version one: renewable energy and resilience planning.")
    pipeline = _make_pipeline(tmp_path)

    first = pipeline.index_document(document_path)
    original_ids = [item.chunk_id for item in pipeline.vector_store.get_chunks(source_filename="changing.txt")]
    assert first.status == "success"

    make_text_file(document_path, "Version two: solar energy and climate adaptation planning.")
    second = pipeline.index_document(document_path)
    updated_ids = [item.chunk_id for item in pipeline.vector_store.get_chunks(source_filename="changing.txt")]

    assert second.status == "success"
    assert updated_ids
    assert original_ids != updated_ids
    assert set(original_ids).isdisjoint(set(updated_ids))


def test_same_filename_different_locations_do_not_collide(tmp_path):
    first_dir = tmp_path / "team-a"
    second_dir = tmp_path / "team-b"
    first_dir.mkdir()
    second_dir.mkdir()

    first_path = make_text_file(first_dir / "report.txt", "Quarterly revenue and operations summary.")
    second_path = make_text_file(second_dir / "report.txt", "Quarterly marketing and customer retention summary.")
    pipeline = _make_pipeline(tmp_path)

    first_result = pipeline.index_document(first_path)
    second_result = pipeline.index_document(second_path)

    assert first_result.status == "success"
    assert second_result.status == "success"

    chunks = pipeline.vector_store.get_chunks(source_filename="report.txt")
    assert len(chunks) == 2
    document_ids = {item.metadata["document_id"] for item in chunks}
    assert len(document_ids) == 2

    hits = pipeline.retrieve("customer retention", top_k=5)
    assert hits and hits[0].metadata["source_filename"] == "report.txt"
    assert any(item.metadata["document_id"] == next(iter(document_ids)) for item in hits)


def test_invalid_and_empty_inputs_are_handled_gracefully(tmp_path):
    pipeline = _make_pipeline(tmp_path)

    empty_path = make_text_file(tmp_path / "empty.txt", "   \n\t  ")
    empty_result = pipeline.index_document(empty_path)
    assert empty_result.status == "empty"

    malformed = tmp_path / "bad.csv"
    malformed.write_text("name,value\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Unsupported file extension"):
        pipeline.index_document(malformed)

    with pytest.raises(ValueError, match="non-empty"):
        pipeline.retrieve("   ")

    with pytest.raises(ValueError, match="positive integer"):
        pipeline.retrieve("query", top_k=0)


def test_bad_pdf_and_embedding_failures_report_errors(tmp_path):
    pipeline = _make_pipeline(tmp_path)

    broken_pdf = tmp_path / "broken.pdf"
    broken_pdf.write_bytes(b"%PDF-1.4\nnot a real pdf")
    broken_result = pipeline.index_document(broken_pdf)
    assert broken_result.status == "error"

    class FailingEmbeddingService(MockEmbeddingService):
        def embed(self, items):
            raise ValueError("simulated embedding failure")

    failing_pipeline = RetrievalPipeline(
        embedding_service=FailingEmbeddingService(),
        vector_store=__import__("app.services.vector_store", fromlist=["ChromaVectorStore"]).ChromaVectorStore(
            persist_directory=tmp_path / "failing-chroma",
            embedding_service=FailingEmbeddingService(),
        ),
    )
    doc_path = make_text_file(tmp_path / "bad-embedding.txt", "Failure should be reported cleanly.")
    result = failing_pipeline.index_document(doc_path)
    assert result.status == "error"
    assert result.error is not None


@pytest.mark.skipif(not os.getenv("RUN_REAL_RETRIEVAL_TESTS"), reason="Optional real-model smoke test")
def test_real_model_retrieval_smoke(tmp_path):
    from app.services.embedding_service import EmbeddingService

    pipeline = RetrievalPipeline(
        embedding_service=EmbeddingService(),
        vector_store=__import__("app.services.vector_store", fromlist=["ChromaVectorStore"]).ChromaVectorStore(
            persist_directory=tmp_path / "real-chroma",
            embedding_service=EmbeddingService(),
        ),
    )
    document_path = make_text_file(tmp_path / "real-model.txt", "Knowledge graphs connect documents, entities, and evidence for better search.")

    result = pipeline.index_document(document_path)
    assert result.status == "success"

    hits = pipeline.retrieve("semantic search and evidence retrieval", top_k=3)
    assert hits
    assert any("knowledge" in item.text.lower() for item in hits)
