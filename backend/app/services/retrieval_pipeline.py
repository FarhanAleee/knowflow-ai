import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.services.document_ingestion import DocumentExtraction, extract_document
from app.services.embedding_service import DEFAULT_MODEL_NAME, EmbeddingService, EmbeddedChunk
from app.services.text_chunking import TextChunk, chunk_document
from app.services.vector_store import ChromaVectorStore, SearchResult

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt"}


@dataclass(frozen=True)
class IndexingResult:
    filename: str
    document_id: str
    status: str
    chunks_indexed: int
    total_chunks: int
    diagnostics: str
    error: str | None = None


class RetrievalPipeline:
    """Connect extraction, chunking, embedding, and vector-store stages."""

    def __init__(
        self,
        embedding_service: EmbeddingService | None = None,
        vector_store: ChromaVectorStore | None = None,
        persist_directory: str | Path | None = None,
        chunk_size: int = 800,
        overlap: int = 150,
    ) -> None:
        self.chunk_size = chunk_size
        self.overlap = overlap
        self.embedding_service = embedding_service or EmbeddingService()
        self.vector_store = vector_store or ChromaVectorStore(
            persist_directory=persist_directory,
            embedding_service=self.embedding_service,
            model_name=self.embedding_service.model_name,
        )

    @staticmethod
    def _normalize_document_id(document_path: str | Path, document_id: str | None = None) -> str:
        if document_id is not None:
            candidate = document_id.strip()
            if not candidate:
                raise ValueError("document_id must not be empty.")
            return candidate
        resolved = Path(document_path).expanduser().resolve()
        return hashlib.sha256(str(resolved).encode("utf-8")).hexdigest()

    @staticmethod
    def _resolve_document_extension(file_path: str | Path) -> str:
        suffix = Path(file_path).suffix.lower()
        if suffix not in SUPPORTED_EXTENSIONS:
            raise ValueError(f"Unsupported file extension: {suffix or '(none)'}. Use .pdf, .docx, or .txt.")
        return suffix

    @staticmethod
    def _chunk_id_for_document(document_id: str, chunk: TextChunk) -> str:
        identity = "\0".join(
            (
                document_id,
                chunk.source_filename,
                chunk.source_format,
                str(chunk.page_number or ""),
                str(chunk.section_number or ""),
                str(chunk.chunk_index),
                chunk.text,
            )
        )
        return hashlib.sha256(identity.encode("utf-8")).hexdigest()

    def _prepare_embedded_chunks(
        self,
        document_id: str,
        chunks: list[TextChunk],
    ) -> list[EmbeddedChunk]:
        if not chunks:
            return []

        embeddings = self.embedding_service.embed(chunks)
        if not embeddings:
            return []

        embedded_chunks: list[EmbeddedChunk] = []
        for chunk, embedded in zip(chunks, embeddings):
            unique_chunk_id = self._chunk_id_for_document(document_id, chunk)
            if isinstance(embedded, EmbeddedChunk):
                vector = embedded.embedding
            else:
                vector = list(embedded)
            embedded_chunks.append(
                EmbeddedChunk(
                    chunk_id=unique_chunk_id,
                    source_filename=chunk.source_filename,
                    source_format=chunk.source_format,
                    page_number=chunk.page_number,
                    section_number=chunk.section_number,
                    section_type=chunk.section_type,
                    chunk_index=chunk.chunk_index,
                    text=chunk.text,
                    character_count=chunk.character_count,
                    embedding=vector,
                    embedding_model=self.embedding_service.model_name,
                    document_id=document_id,
                )
            )
        return embedded_chunks

    def index_document(self, file_path: str | Path, document_id: str | None = None) -> IndexingResult:
        if file_path is None:
            raise ValueError("file_path must not be empty.")

        source = Path(file_path).expanduser()
        if not source.exists() or not source.is_file():
            raise FileNotFoundError(f"File not found: {source}")

        extension = self._resolve_document_extension(source)
        resolved_path = source.resolve()
        normalized_document_id = self._normalize_document_id(resolved_path, document_id)

        try:
            extracted_document = extract_document(resolved_path)
        except Exception as exc:  # pragma: no cover - defensive fallback
            return IndexingResult(
                filename=source.name,
                document_id=normalized_document_id,
                status="error",
                chunks_indexed=0,
                total_chunks=0,
                diagnostics="Extraction failed before processing.",
                error=str(exc),
            )

        if extracted_document.status == "error":
            return IndexingResult(
                filename=extracted_document.filename,
                document_id=normalized_document_id,
                status="error",
                chunks_indexed=0,
                total_chunks=0,
                diagnostics=extracted_document.error or "Document extraction reported an error.",
                error=extracted_document.error,
            )

        if not extracted_document.content.strip() and not extracted_document.pages and not extracted_document.sections:
            return IndexingResult(
                filename=extracted_document.filename,
                document_id=normalized_document_id,
                status="empty",
                chunks_indexed=0,
                total_chunks=0,
                diagnostics="Document contains no extractable text.",
            )

        try:
            chunks = chunk_document(extracted_document, chunk_size=self.chunk_size, overlap=self.overlap)
        except ValueError as exc:
            return IndexingResult(
                filename=extracted_document.filename,
                document_id=normalized_document_id,
                status="error",
                chunks_indexed=0,
                total_chunks=0,
                diagnostics="Chunking configuration is invalid.",
                error=str(exc),
            )

        if not chunks:
            return IndexingResult(
                filename=extracted_document.filename,
                document_id=normalized_document_id,
                status="empty",
                chunks_indexed=0,
                total_chunks=0,
                diagnostics="Document produced no chunks with searchable text.",
            )

        existing_ids = [
            record.chunk_id
            for record in self.vector_store.get_chunks(source_filename=extracted_document.filename)
            if record.metadata.get("document_id") == normalized_document_id
        ]

        try:
            embedded_chunks = self._prepare_embedded_chunks(normalized_document_id, chunks)
            if not embedded_chunks:
                return IndexingResult(
                    filename=extracted_document.filename,
                    document_id=normalized_document_id,
                    status="empty",
                    chunks_indexed=0,
                    total_chunks=len(chunks),
                    diagnostics="No searchable chunks were created after embedding.",
                )

            self.vector_store.upsert(embedded_chunks)
            stale_ids = [chunk_id for chunk_id in existing_ids if chunk_id not in {item.chunk_id for item in embedded_chunks}]
            if stale_ids:
                self.vector_store.delete(stale_ids)
        except Exception as exc:  # pragma: no cover - defensive fallback
            return IndexingResult(
                filename=extracted_document.filename,
                document_id=normalized_document_id,
                status="error",
                chunks_indexed=0,
                total_chunks=len(chunks),
                diagnostics="Embedding or storage failed while indexing the document.",
                error=str(exc),
            )

        return IndexingResult(
            filename=extracted_document.filename,
            document_id=normalized_document_id,
            status="success",
            chunks_indexed=len(embedded_chunks),
            total_chunks=len(chunks),
            diagnostics=(
                f"Indexed {len(embedded_chunks)} chunk(s) for {extracted_document.filename} "
                f"with document_id {normalized_document_id}."
            ),
        )

    def retrieve(
        self,
        query: str,
        top_k: int = 3,
        source_filename: str | None = None,
        source_format: str | None = None,
        document_id: str | None = None,
    ) -> list[SearchResult]:
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query must be a non-empty string.")
        if not isinstance(top_k, int) or isinstance(top_k, bool) or top_k <= 0:
            raise ValueError("top_k must be a positive integer.")

        if self.vector_store.count() == 0:
            return []

        embeddings = self.embedding_service.embed([query.strip()])
        if not embeddings or not isinstance(embeddings[0], list):
            raise ValueError("EmbeddingService returned an invalid query embedding.")

        return self.vector_store.search(
            embeddings[0],
            n_results=top_k,
            source_filename=source_filename,
            source_format=source_format,
            document_id=document_id,
        )


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Index a document and query it with semantic retrieval.")
    parser.add_argument("document_path", help="Path to a .pdf, .docx, or .txt document")
    parser.add_argument("query", help="Question to run against indexed content")
    parser.add_argument("--top-k", type=int, default=3, help="Number of results to show")
    parser.add_argument("--persist-directory", default=None, help="Optional ChromaDB persistence directory")
    args = parser.parse_args()

    pipeline = RetrievalPipeline(persist_directory=args.persist_directory)
    result = pipeline.index_document(args.document_path)
    print(f"Index status: {result.status}")
    print(f"Chunks indexed: {result.chunks_indexed}/{result.total_chunks}")
    if result.error:
        print(f"Error: {result.error}")
    print(result.diagnostics)

    results = pipeline.retrieve(args.query, top_k=args.top_k)
    if not results:
        print("No relevant chunks were found.")
        return

    for index, item in enumerate(results, start=1):
        metadata = item.metadata
        page_label = metadata.get("page_number")
        section_label = metadata.get("section_number")
        ref = f"page {page_label}" if page_label is not None else f"section {section_label}" if section_label is not None else "document"
        print(f"\nResult {index}: {metadata.get('source_filename')} ({ref})")
        print(f"Chunk ID: {item.chunk_id}")
        print(f"Similarity: {item.similarity:.4f} | Distance: {item.distance:.4f}")
        print(item.text[:400])


if __name__ == "__main__":
    main()
