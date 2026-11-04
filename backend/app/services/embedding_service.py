import math
from dataclasses import dataclass
from typing import Protocol, Sequence, overload

from app.services.text_chunking import TextChunk


DEFAULT_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"


class _SentenceTransformerModel(Protocol):
    def encode(
        self,
        sentences: list[str],
        *,
        batch_size: int,
        normalize_embeddings: bool,
        convert_to_numpy: bool,
        show_progress_bar: bool,
    ) -> object: ...


@dataclass(frozen=True)
class EmbeddedChunk:
    chunk_id: str
    source_filename: str
    source_format: str
    page_number: int | None
    section_number: int | None
    section_type: str | None
    chunk_index: int
    text: str
    character_count: int
    embedding: list[float]
    embedding_model: str = DEFAULT_MODEL_NAME
    document_id: str | None = None


def _load_sentence_transformer(
    model_name: str, device: str
) -> _SentenceTransformerModel:
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(model_name, device=device)


def cosine_similarity(first: Sequence[float], second: Sequence[float]) -> float:
    """Return cosine similarity for two equally sized, non-zero vectors."""
    if isinstance(first, (str, bytes)) or isinstance(second, (str, bytes)):
        raise ValueError("Embeddings must be numeric vectors.")

    try:
        first_values = [float(value) for value in first]
        second_values = [float(value) for value in second]
    except (TypeError, ValueError) as error:
        raise ValueError("Embeddings must be numeric vectors.") from error

    if not first_values or len(first_values) != len(second_values):
        raise ValueError("Embeddings must have the same nonzero dimension.")
    if not all(math.isfinite(value) for value in first_values + second_values):
        raise ValueError("Embeddings must contain only finite values.")

    first_norm = math.sqrt(sum(value * value for value in first_values))
    second_norm = math.sqrt(sum(value * value for value in second_values))
    if first_norm == 0 or second_norm == 0:
        raise ValueError("Cosine similarity is undefined for a zero vector.")

    similarity = sum(
        first_value * second_value
        for first_value, second_value in zip(first_values, second_values)
    ) / (first_norm * second_norm)
    return max(-1.0, min(1.0, similarity))


class EmbeddingService:
    """Lazily load a Sentence Transformers model and embed text or chunks."""

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL_NAME,
        batch_size: int = 32,
        device: str = "cpu",
    ) -> None:
        if batch_size <= 0:
            raise ValueError("batch_size must be positive.")
        if not model_name.strip():
            raise ValueError("model_name must not be empty.")
        if not device.strip():
            raise ValueError("device must not be empty.")

        self.model_name = model_name
        self.batch_size = batch_size
        self.device = device
        self._model: _SentenceTransformerModel | None = None
        self._embedding_dimension: int | None = None

    @property
    def embedding_dimension(self) -> int | None:
        """Return the dimension after the model has produced its first vector."""
        return self._embedding_dimension

    def _get_model(self) -> _SentenceTransformerModel:
        if self._model is None:
            self._model = _load_sentence_transformer(self.model_name, self.device)
        return self._model

    @staticmethod
    def _normalize_vectors(encoded: object, expected_count: int) -> list[list[float]]:
        if hasattr(encoded, "tolist"):
            encoded = encoded.tolist()
        if not isinstance(encoded, (list, tuple)) or len(encoded) != expected_count:
            raise ValueError("The embedding model returned an unexpected batch shape.")

        vectors: list[list[float]] = []
        expected_dimension: int | None = None
        for row in encoded:
            if hasattr(row, "tolist"):
                row = row.tolist()
            if not isinstance(row, (list, tuple)) or not row:
                raise ValueError("The embedding model returned an invalid vector.")

            try:
                vector = [float(value) for value in row]
            except (TypeError, ValueError) as error:
                raise ValueError("The embedding model returned non-numeric values.") from error

            if not all(math.isfinite(value) for value in vector):
                raise ValueError("The embedding model returned non-finite values.")
            if expected_dimension is None:
                expected_dimension = len(vector)
            elif len(vector) != expected_dimension:
                raise ValueError("The embedding model returned inconsistent dimensions.")

            norm = math.sqrt(sum(value * value for value in vector))
            if norm == 0:
                raise ValueError("The embedding model returned a zero vector.")
            vectors.append([value / norm for value in vector])

        return vectors

    def _embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        model = self._get_model()
        embeddings: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = texts[start : start + self.batch_size]
            encoded = model.encode(
                batch,
                batch_size=self.batch_size,
                normalize_embeddings=True,
                convert_to_numpy=True,
                show_progress_bar=False,
            )
            vectors = self._normalize_vectors(encoded, len(batch))
            dimension = len(vectors[0])
            if self._embedding_dimension is None:
                self._embedding_dimension = dimension
            elif dimension != self._embedding_dimension:
                raise ValueError("The embedding model returned inconsistent dimensions.")
            embeddings.extend(vectors)

        return embeddings

    @overload
    def embed(self, items: Sequence[str]) -> list[list[float]]: ...

    @overload
    def embed(self, items: Sequence[TextChunk]) -> list[EmbeddedChunk]: ...

    def embed(
        self, items: Sequence[str] | Sequence[TextChunk]
    ) -> list[list[float]] | list[EmbeddedChunk]:
        """Embed a sequence of strings or TextChunk objects in batches."""
        if not items:
            return []

        first_item = items[0]
        if isinstance(first_item, str):
            if any(not isinstance(item, str) for item in items):
                raise TypeError("Input must contain only strings or only TextChunk objects.")
            texts = list(items)
            for index, text in enumerate(texts):
                if not text.strip():
                    raise ValueError(f"Text at index {index} must not be empty.")
            return self._embed_texts(texts)

        if isinstance(first_item, TextChunk):
            if any(not isinstance(item, TextChunk) for item in items):
                raise TypeError("Input must contain only strings or only TextChunk objects.")
            chunks = list(items)
            for index, chunk in enumerate(chunks):
                if not chunk.text.strip():
                    raise ValueError(f"TextChunk at index {index} must not be empty.")
            vectors = self._embed_texts([chunk.text for chunk in chunks])
            return [
                EmbeddedChunk(
                    chunk_id=chunk.chunk_id,
                    source_filename=chunk.source_filename,
                    source_format=chunk.source_format,
                    page_number=chunk.page_number,
                    section_number=chunk.section_number,
                    section_type=chunk.section_type,
                    chunk_index=chunk.chunk_index,
                    text=chunk.text,
                    character_count=chunk.character_count,
                    embedding=vector,
                    embedding_model=self.model_name,
                )
                for chunk, vector in zip(chunks, vectors)
            ]

        raise TypeError("Input must contain only strings or only TextChunk objects.")
