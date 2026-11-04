import math
import os

import pytest

from app.services.embedding_service import (
    DEFAULT_MODEL_NAME,
    EmbeddedChunk,
    EmbeddingService,
    cosine_similarity,
)
from app.services.text_chunking import TextChunk


class FakeModel:
    def __init__(self):
        self.calls = []

    def encode(
        self,
        texts,
        *,
        batch_size,
        normalize_embeddings,
        convert_to_numpy,
        show_progress_bar,
    ):
        self.calls.append(
            {
                "texts": list(texts),
                "batch_size": batch_size,
                "normalize_embeddings": normalize_embeddings,
                "convert_to_numpy": convert_to_numpy,
                "show_progress_bar": show_progress_bar,
            }
        )
        return [[len(text), 3.0, 4.0] for text in texts]


def sample_chunk(chunk_id: str = "chunk-1") -> TextChunk:
    text = "A company policy."
    return TextChunk(
        chunk_id=chunk_id,
        source_filename="handbook.pdf",
        source_format="PDF",
        page_number=2,
        section_number=None,
        section_type=None,
        chunk_index=1,
        text=text,
        character_count=len(text),
    )


def test_embeddings_have_consistent_dimensions_and_are_normalized(monkeypatch):
    model = FakeModel()
    monkeypatch.setattr(
        "app.services.embedding_service._load_sentence_transformer",
        lambda model_name, device: model,
    )
    service = EmbeddingService()

    embeddings = service.embed(["first", "second"])

    assert len(embeddings) == 2
    assert all(len(vector) == 3 for vector in embeddings)
    assert service.embedding_dimension == 3
    assert all(math.isclose(math.sqrt(sum(value * value for value in vector)), 1.0) for vector in embeddings)
    assert model.calls[0]["normalize_embeddings"] is True
    assert model.calls[0]["batch_size"] == 32


def test_embeddings_are_generated_in_batches(monkeypatch):
    model = FakeModel()
    monkeypatch.setattr(
        "app.services.embedding_service._load_sentence_transformer",
        lambda model_name, device: model,
    )
    service = EmbeddingService(batch_size=2)

    result = service.embed(["one", "two", "three", "four", "five"])

    assert len(result) == 5
    assert [len(call["texts"]) for call in model.calls] == [2, 2, 1]


def test_empty_input_returns_without_loading_model(monkeypatch):
    def fail_if_loaded(model_name, device):
        raise AssertionError("Model should not be loaded for empty input.")

    monkeypatch.setattr(
        "app.services.embedding_service._load_sentence_transformer",
        fail_if_loaded,
    )

    assert EmbeddingService().embed([]) == []


@pytest.mark.parametrize("text", ["", "  ", "\n"])
def test_invalid_empty_text_is_reported(text, monkeypatch):
    model = FakeModel()
    monkeypatch.setattr(
        "app.services.embedding_service._load_sentence_transformer",
        lambda model_name, device: model,
    )

    with pytest.raises(ValueError, match="must not be empty"):
        EmbeddingService().embed(["valid", text])

    assert model.calls == []


def test_metadata_is_preserved_when_embedding_chunks(monkeypatch):
    model = FakeModel()
    monkeypatch.setattr(
        "app.services.embedding_service._load_sentence_transformer",
        lambda model_name, device: model,
    )
    chunk = sample_chunk()

    result = EmbeddingService().embed([chunk])

    assert len(result) == 1
    embedded = result[0]
    assert isinstance(embedded, EmbeddedChunk)
    assert embedded.chunk_id == chunk.chunk_id
    assert embedded.source_filename == chunk.source_filename
    assert embedded.source_format == chunk.source_format
    assert embedded.page_number == chunk.page_number
    assert embedded.section_number == chunk.section_number
    assert embedded.section_type == chunk.section_type
    assert embedded.chunk_index == chunk.chunk_index
    assert embedded.text == chunk.text
    assert embedded.character_count == chunk.character_count
    assert len(embedded.embedding) == 3


def test_model_loads_lazily_once_and_is_reused(monkeypatch):
    model = FakeModel()
    loaded_models = []

    def load_model(model_name, device):
        loaded_models.append((model_name, device))
        return model

    monkeypatch.setattr(
        "app.services.embedding_service._load_sentence_transformer",
        load_model,
    )
    service = EmbeddingService()

    assert loaded_models == []
    service.embed(["first"])
    service.embed(["second"])

    assert loaded_models == [(DEFAULT_MODEL_NAME, "cpu")]
    assert len(model.calls) == 2


def test_cosine_similarity_and_shape_validation():
    assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)
    assert cosine_similarity([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)

    with pytest.raises(ValueError, match="same nonzero dimension"):
        cosine_similarity([1.0], [1.0, 2.0])
    with pytest.raises(ValueError, match="zero vector"):
        cosine_similarity([0.0, 0.0], [1.0, 0.0])


def test_rejects_mixed_and_non_text_inputs(monkeypatch):
    model = FakeModel()
    monkeypatch.setattr(
        "app.services.embedding_service._load_sentence_transformer",
        lambda model_name, device: model,
    )

    with pytest.raises(TypeError, match="only strings"):
        EmbeddingService().embed(["valid", 123])

    assert model.calls == []


def test_model_dimension_must_remain_consistent(monkeypatch):
    class ChangingModel(FakeModel):
        def encode(self, texts, **kwargs):
            self.calls.append(list(texts))
            dimension = 3 if len(self.calls) == 1 else 4
            return [[1.0] * dimension for _ in texts]

    model = ChangingModel()
    monkeypatch.setattr(
        "app.services.embedding_service._load_sentence_transformer",
        lambda model_name, device: model,
    )
    service = EmbeddingService(batch_size=1)

    with pytest.raises(ValueError, match="inconsistent dimensions"):
        service.embed(["first", "second"])


@pytest.mark.skipif(
    os.environ.get("RUN_REAL_EMBEDDING_TESTS") != "1",
    reason="Optional network/model-download smoke test; set RUN_REAL_EMBEDDING_TESTS=1 to run.",
)
def test_real_model_smoke():
    service = EmbeddingService()
    embeddings = service.embed(["KnowFlow AI company knowledge search."])

    assert len(embeddings) == 1
    assert len(embeddings[0]) == 384
    assert math.sqrt(sum(value * value for value in embeddings[0])) == pytest.approx(1.0)
