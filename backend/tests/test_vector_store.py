import math

import pytest

from app.services.embedding_service import EmbeddedChunk, EmbeddingService
from app.services.vector_store import ChromaVectorStore


def make_embedding(values: tuple[float, ...]) -> list[float]:
    vector = list(values) + [0.0] * (384 - len(values))
    norm = math.sqrt(sum(value * value for value in vector))
    return [value / norm for value in vector]


def make_chunk(
    chunk_id: str,
    embedding: list[float],
    *,
    filename: str = "handbook.pdf",
    source_format: str = "PDF",
    page_number: int | None = 1,
    section_number: int | None = None,
) -> EmbeddedChunk:
    text = f"Document text for {chunk_id}"
    return EmbeddedChunk(
        chunk_id=chunk_id,
        source_filename=filename,
        source_format=source_format,
        page_number=page_number,
        section_number=section_number,
        section_type="paragraph" if section_number is not None else None,
        chunk_index=1,
        text=text,
        character_count=len(text),
        embedding=embedding,
    )


def test_upsert_and_repeated_ids_replace_existing_records(tmp_path):
    store = ChromaVectorStore(persist_directory=tmp_path)
    original = make_chunk("same-id", make_embedding((1.0, 0.0)))

    assert store.upsert([original]) == 1
    assert store.count() == 1

    updated = EmbeddedChunk(
        **{
            **original.__dict__,
            "text": "Updated text",
            "character_count": len("Updated text"),
            "embedding": make_embedding((0.9, 0.1)),
        }
    )
    assert store.upsert([updated]) == 1
    assert store.count() == 1
    assert store.get_chunks(ids=["same-id"])[0].text == "Updated text"


def test_persistence_survives_store_reinitialization(tmp_path):
    chunk = make_chunk("persistent", make_embedding((1.0, 0.0)))
    first_store = ChromaVectorStore(persist_directory=tmp_path)
    first_store.upsert([chunk])

    reopened_store = ChromaVectorStore(persist_directory=tmp_path)

    assert reopened_store.count() == 1
    stored = reopened_store.get_chunks(ids=["persistent"])
    assert stored[0].text == chunk.text
    assert stored[0].metadata["page_number"] == 1
    assert len(stored[0].embedding) == 384


def test_search_orders_results_by_cosine_relevance(tmp_path):
    store = ChromaVectorStore(persist_directory=tmp_path)
    store.upsert(
        [
            make_chunk("opposite", make_embedding((-1.0, 0.0))),
            make_chunk("similar", make_embedding((0.9, 0.1))),
            make_chunk("orthogonal", make_embedding((0.0, 1.0))),
        ]
    )

    results = store.search(make_embedding((1.0, 0.0)), n_results=10)

    assert [result.chunk_id for result in results] == [
        "similar",
        "orthogonal",
        "opposite",
    ]
    assert results[0].similarity > results[1].similarity > results[2].similarity
    assert results[0].distance < results[1].distance < results[2].distance
    assert results[0].text == "Document text for similar"


def test_search_filters_by_source_filename_and_format(tmp_path):
    store = ChromaVectorStore(persist_directory=tmp_path)
    store.upsert(
        [
            make_chunk("pdf-match", make_embedding((1.0, 0.0)), filename="a.pdf"),
            make_chunk(
                "docx-match",
                make_embedding((1.0, 0.0)),
                filename="a.docx",
                source_format="DOCX",
                page_number=None,
                section_number=2,
            ),
            make_chunk("other", make_embedding((1.0, 0.0)), filename="b.pdf"),
        ]
    )

    results = store.search(
        make_embedding((1.0, 0.0)),
        source_filename="a.docx",
        source_format="docx",
    )

    assert [result.chunk_id for result in results] == ["docx-match"]
    assert results[0].metadata["section_number"] == 2
    assert "page_number" not in results[0].metadata


def test_retrieval_and_delete_by_id(tmp_path):
    store = ChromaVectorStore(persist_directory=tmp_path)
    store.upsert(
        [
            make_chunk("first", make_embedding((1.0, 0.0))),
            make_chunk("second", make_embedding((0.0, 1.0))),
        ]
    )

    assert len(store.get_chunks(source_filename="handbook.pdf", limit=1)) == 1
    assert store.delete(["first", "missing", "first"]) == 1
    assert store.count() == 1
    assert store.get_chunks(ids=["first"]) == []
    assert store.delete([]) == 0


def test_empty_collection_and_empty_upsert_are_safe(tmp_path):
    store = ChromaVectorStore(persist_directory=tmp_path)

    assert store.upsert([]) == 0
    assert store.search(make_embedding((1.0, 0.0))) == []
    assert store.get_chunks() == []
    assert store.count() == 0
    assert store.delete([]) == 0


@pytest.mark.parametrize(
    "embedding",
    [
        [1.0, 0.0],
        [float("nan")] + [0.0] * 383,
        [float("inf")] + [0.0] * 383,
        [0.0] * 384,
    ],
)
def test_upsert_rejects_invalid_embeddings(tmp_path, embedding):
    store = ChromaVectorStore(persist_directory=tmp_path)
    with pytest.raises(ValueError):
        store.upsert([make_chunk("invalid", embedding)])
    assert store.count() == 0


@pytest.mark.parametrize("limit", [0, -1, True, 1.5])
def test_search_validates_result_limit(tmp_path, limit):
    store = ChromaVectorStore(persist_directory=tmp_path)
    with pytest.raises(ValueError, match="positive integer"):
        store.search(make_embedding((1.0, 0.0)), n_results=limit)


def test_search_rejects_wrong_dimension_and_non_finite_query(tmp_path):
    store = ChromaVectorStore(persist_directory=tmp_path)
    with pytest.raises(ValueError, match="384 dimensions"):
        store.search([1.0, 0.0])
    with pytest.raises(ValueError, match="finite"):
        store.search([float("nan")] + [0.0] * 383)


def test_section_metadata_omits_none_fields(tmp_path):
    store = ChromaVectorStore(persist_directory=tmp_path)
    chunk = make_chunk(
        "txt-section",
        make_embedding((1.0, 0.0)),
        filename="notes.txt",
        source_format="TXT",
        page_number=None,
        section_number=1,
    )

    store.upsert([chunk])
    metadata = store.get_chunks(ids=["txt-section"])[0].metadata

    assert metadata["source_format"] == "TXT"
    assert metadata["section_number"] == 1
    assert "page_number" not in metadata


def test_store_rejects_incompatible_model_for_existing_collection(tmp_path):
    ChromaVectorStore(persist_directory=tmp_path)

    with pytest.raises(ValueError, match="embedding_model"):
        ChromaVectorStore(
            persist_directory=tmp_path,
            model_name="different-embedding-model",
        )


def test_store_rejects_incompatible_dimension_for_existing_collection(tmp_path):
    ChromaVectorStore(persist_directory=tmp_path)

    with pytest.raises(ValueError, match="embedding_dimension"):
        ChromaVectorStore(persist_directory=tmp_path, embedding_dimension=128)


def test_upsert_rejects_chunks_from_another_embedding_model(tmp_path):
    store = ChromaVectorStore(persist_directory=tmp_path)
    chunk = EmbeddedChunk(
        **{
            **make_chunk("wrong-model", make_embedding((1.0, 0.0))).__dict__,
            "embedding_model": "different-embedding-model",
        }
    )

    with pytest.raises(ValueError, match="embedding model"):
        store.upsert([chunk])
    assert store.count() == 0


def test_relative_storage_path_is_resolved_from_backend_root(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.vector_store._BACKEND_ROOT", tmp_path)

    store = ChromaVectorStore(persist_directory="local-vector-data")

    assert store.persist_directory == (tmp_path / "local-vector-data").resolve()


def test_search_by_text_uses_configured_embedding_service(tmp_path):
    class FakeEmbeddingService:
        model_name = "sentence-transformers/all-MiniLM-L6-v2"

        def embed(self, texts):
            assert texts == ["a query"]
            return [make_embedding((1.0, 0.0))]

    service = FakeEmbeddingService()
    store = ChromaVectorStore(
        persist_directory=tmp_path,
        embedding_service=service,  # type: ignore[arg-type]
    )
    store.upsert([make_chunk("result", make_embedding((1.0, 0.0)))])

    assert [result.chunk_id for result in store.search_by_text("a query")] == ["result"]


def test_search_by_text_rejects_empty_query_and_missing_service(tmp_path):
    store = ChromaVectorStore(persist_directory=tmp_path)
    with pytest.raises(ValueError, match="must not be empty"):
        store.search_by_text("  ")
    with pytest.raises(RuntimeError, match="requires an EmbeddingService"):
        store.search_by_text("query")
