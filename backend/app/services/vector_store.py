import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import chromadb

from app.services.embedding_service import (
    DEFAULT_MODEL_NAME,
    EmbeddingService,
    EmbeddedChunk,
)


COLLECTION_NAME = "knowflow_documents"
DEFAULT_EMBEDDING_DIMENSION = 384
_BACKEND_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class StoredChunk:
    chunk_id: str
    text: str
    metadata: dict[str, str | int]
    embedding: list[float]


@dataclass(frozen=True)
class SearchResult:
    chunk_id: str
    text: str
    metadata: dict[str, str | int]
    distance: float
    similarity: float


class ChromaVectorStore:
    """Persist and search explicit text embeddings in a cosine Chroma collection."""

    def __init__(
        self,
        persist_directory: str | Path | None = None,
        embedding_service: EmbeddingService | None = None,
        model_name: str = DEFAULT_MODEL_NAME,
        embedding_dimension: int = DEFAULT_EMBEDDING_DIMENSION,
        collection_name: str = COLLECTION_NAME,
    ) -> None:
        if not model_name.strip():
            raise ValueError("model_name must not be empty.")
        if (
            not isinstance(embedding_dimension, int)
            or isinstance(embedding_dimension, bool)
            or embedding_dimension <= 0
        ):
            raise ValueError("embedding_dimension must be a positive integer.")
        if not collection_name.strip():
            raise ValueError("collection_name must not be empty.")
        if embedding_service is not None and embedding_service.model_name != model_name:
            raise ValueError("Embedding service model does not match vector store model.")

        configured_path = persist_directory or os.environ.get("KNOWFLOW_CHROMA_PATH")
        if configured_path is None:
            path = _BACKEND_ROOT / "data" / "chroma"
        else:
            path = Path(configured_path).expanduser()
            if not path.is_absolute():
                path = _BACKEND_ROOT / path
        self.persist_directory = path.resolve()
        self.persist_directory.mkdir(parents=True, exist_ok=True)

        self.model_name = model_name
        self.embedding_dimension = embedding_dimension
        self.embedding_service = embedding_service
        self.collection_name = collection_name

        self._client = chromadb.PersistentClient(path=str(self.persist_directory))
        self._collection = self._client.get_or_create_collection(
            name=collection_name,
            embedding_function=None,
            metadata={
                "hnsw:space": "cosine",
                "embedding_model": model_name,
                "embedding_dimension": embedding_dimension,
            },
        )
        self._validate_collection_compatibility()

    def _validate_collection_compatibility(self) -> None:
        metadata = self._collection.metadata or {}
        expected = {
            "hnsw:space": "cosine",
            "embedding_model": self.model_name,
            "embedding_dimension": self.embedding_dimension,
        }
        for key, value in expected.items():
            if metadata.get(key) != value:
                raise ValueError(
                    f"Collection {self.collection_name!r} has incompatible {key!r} metadata."
                )

        if self._collection.count():
            stored = self._collection.get(limit=1, include=["embeddings"])
            embeddings = stored.get("embeddings")
            if embeddings is not None and len(embeddings):
                if len(embeddings[0]) != self.embedding_dimension:
                    raise ValueError("Stored collection embedding dimension is incompatible.")

    def _validate_vector(self, embedding: Sequence[float], name: str) -> list[float]:
        if isinstance(embedding, (str, bytes)):
            raise ValueError(f"{name} must be a numeric vector.")
        try:
            vector = [float(value) for value in embedding]
        except (TypeError, ValueError) as error:
            raise ValueError(f"{name} must be a numeric vector.") from error

        if len(vector) != self.embedding_dimension:
            raise ValueError(
                f"{name} must have {self.embedding_dimension} dimensions; got {len(vector)}."
            )
        if not all(math.isfinite(value) for value in vector):
            raise ValueError(f"{name} must contain only finite values.")
        if not any(value != 0 for value in vector):
            raise ValueError(f"{name} must not be a zero vector for cosine distance.")
        return vector

    def _metadata_for(self, chunk: EmbeddedChunk) -> dict[str, str | int]:
        if not chunk.source_filename:
            raise ValueError("Chunk source_filename must not be empty.")
        if not chunk.text.strip():
            raise ValueError("Chunk text must not be empty.")
        if chunk.source_format.upper() not in {"PDF", "DOCX", "TXT"}:
            raise ValueError(f"Unsupported source format: {chunk.source_format!r}.")
        if not chunk.chunk_id:
            raise ValueError("Chunk ID must not be empty.")
        if chunk.embedding_model != self.model_name:
            raise ValueError("Chunk embedding model does not match vector store model.")

        metadata: dict[str, str | int] = {
            "source_filename": chunk.source_filename,
            "source_format": chunk.source_format.upper(),
            "chunk_index": chunk.chunk_index,
            "character_count": chunk.character_count,
        }
        if chunk.page_number is not None:
            metadata["page_number"] = chunk.page_number
        if chunk.section_number is not None:
            metadata["section_number"] = chunk.section_number
        if chunk.section_type is not None:
            metadata["section_type"] = chunk.section_type
        if getattr(chunk, "document_id", None):
            metadata["document_id"] = chunk.document_id
        return metadata

    @staticmethod
    def _where(
        source_filename: str | None,
        source_format: str | None,
        document_id: str | None = None,
    ) -> dict[str, Any] | None:
        predicates: list[dict[str, str]] = []
        if source_filename is not None:
            predicates.append({"source_filename": source_filename})
        if source_format is not None:
            normalized_format = source_format.upper()
            if normalized_format not in {"PDF", "DOCX", "TXT"}:
                raise ValueError(f"Unsupported source format: {source_format!r}.")
            predicates.append({"source_format": normalized_format})
        if document_id is not None:
            predicates.append({"document_id": document_id})

        if not predicates:
            return None
        if len(predicates) == 1:
            return predicates[0]
        return {"$and": predicates}

    @staticmethod
    def _validate_limit(limit: int, name: str = "n_results") -> None:
        if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
            raise ValueError(f"{name} must be a positive integer.")

    def upsert(self, chunks: Sequence[EmbeddedChunk]) -> int:
        """Insert or replace embedded chunks by their deterministic IDs."""
        if not chunks:
            return 0

        ids: list[str] = []
        documents: list[str] = []
        metadatas: list[dict[str, str | int]] = []
        embeddings: list[list[float]] = []
        seen_ids: set[str] = set()

        for chunk in chunks:
            if chunk.chunk_id in seen_ids:
                raise ValueError(f"Duplicate chunk ID in input: {chunk.chunk_id!r}.")
            seen_ids.add(chunk.chunk_id)
            ids.append(chunk.chunk_id)
            documents.append(chunk.text)
            metadatas.append(self._metadata_for(chunk))
            embeddings.append(self._validate_vector(chunk.embedding, "Chunk embedding"))

        self._collection.upsert(
            ids=ids,
            documents=documents,
            metadatas=metadatas,
            embeddings=embeddings,
        )
        return len(ids)

    def search(
        self,
        query_embedding: Sequence[float],
        n_results: int = 5,
        source_filename: str | None = None,
        source_format: str | None = None,
        document_id: str | None = None,
    ) -> list[SearchResult]:
        """Search by an explicit query vector, closest cosine result first."""
        self._validate_limit(n_results)
        vector = self._validate_vector(query_embedding, "Query embedding")
        where = self._where(source_filename, source_format, document_id)
        if self._collection.count() == 0:
            return []

        query_arguments: dict[str, Any] = {
            "query_embeddings": [vector],
            "n_results": n_results,
            "include": ["documents", "metadatas", "distances"],
        }
        if where is not None:
            query_arguments["where"] = where
        results = self._collection.query(**query_arguments)

        ids = results.get("ids", [[]])[0]
        documents = results.get("documents", [[]])[0] or []
        metadatas = results.get("metadatas", [[]])[0] or []
        distances = results.get("distances", [[]])[0] or []
        found = [
            SearchResult(
                chunk_id=chunk_id,
                text=text,
                metadata=metadata,
                distance=float(distance),
                similarity=max(-1.0, min(1.0, 1.0 - float(distance))),
            )
            for chunk_id, text, metadata, distance in zip(
                ids, documents, metadatas, distances
            )
        ]
        return sorted(found, key=lambda result: result.distance)

    def search_by_text(
        self,
        query_text: str,
        n_results: int = 5,
        source_filename: str | None = None,
        source_format: str | None = None,
    ) -> list[SearchResult]:
        """Embed a text query with the configured EmbeddingService and search."""
        if not isinstance(query_text, str) or not query_text.strip():
            raise ValueError("query_text must not be empty.")
        if self.embedding_service is None:
            raise RuntimeError("search_by_text requires an EmbeddingService.")
        embeddings = self.embedding_service.embed([query_text])
        if (
            not embeddings
            or not isinstance(embeddings[0], list)
            or any(not isinstance(value, (int, float)) for value in embeddings[0])
        ):
            raise ValueError("EmbeddingService returned an invalid query embedding.")
        return self.search(
            embeddings[0],
            n_results=n_results,
            source_filename=source_filename,
            source_format=source_format,
        )

    def get_chunks(
        self,
        ids: Sequence[str] | None = None,
        limit: int | None = None,
        source_filename: str | None = None,
        source_format: str | None = None,
    ) -> list[StoredChunk]:
        """Retrieve stored text, metadata, and embeddings."""
        if ids is not None and not ids:
            return []
        if limit is not None:
            self._validate_limit(limit, "limit")
        where = self._where(source_filename, source_format)

        arguments: dict[str, Any] = {"include": ["documents", "metadatas", "embeddings"]}
        if ids is not None:
            arguments["ids"] = list(ids)
        if limit is not None:
            arguments["limit"] = limit
        if where is not None:
            arguments["where"] = where

        results = self._collection.get(**arguments)
        documents = results.get("documents") or []
        metadatas = results.get("metadatas") or []
        embeddings = results.get("embeddings")
        if embeddings is None:
            embeddings = [[] for _ in results.get("ids", [])]

        return [
            StoredChunk(
                chunk_id=chunk_id,
                text=text,
                metadata=metadata,
                embedding=[float(value) for value in embedding],
            )
            for chunk_id, text, metadata, embedding in zip(
                results.get("ids", []), documents, metadatas, embeddings
            )
        ]

    def delete(self, ids: Sequence[str]) -> int:
        """Delete chunks by ID and return the number of records removed."""
        if not ids:
            return 0
        existing = self._collection.get(ids=list(dict.fromkeys(ids)), include=[])
        removed_count = len(existing.get("ids", []))
        if removed_count:
            self._collection.delete(ids=list(dict.fromkeys(ids)))
        return removed_count

    def count(self) -> int:
        """Return the number of records in the collection."""
        return self._collection.count()
