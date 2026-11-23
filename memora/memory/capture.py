"""
MEMORA Memory Capture

Knowledge capture functionality for AI agents.
Provides `memorize` tool for storing information with automatic embedding.
"""

import uuid
import time
from dataclasses import dataclass
from typing import Optional, List, Dict, Any

from memora.config import get_config
from memora.embeddings.base import EmbeddingProvider
from memora.embeddings import get_default_provider
from memora.storage.metadata_store import MetadataStore, ChunkRecord, compute_hash, generate_chunk_id
from memora.storage.vector_store import VectorStore
from memora.ingestion.chunker import Chunker, TextChunk, chunk_vault_file


@dataclass
class CaptureResult:
    """Result of a capture operation."""
    success: bool
    chunk_ids: List[str]
    message: str
    chunk_count: int = 0


class MemoryCapture:
    """
    High-level memory capture for AI agents.

    Captures knowledge by:
    1. Chunking the content
    2. Generating embeddings
    3. Storing in both SQLite (metadata + FTS) and ChromaDB (vectors)
    """

    def __init__(self,
                 metadata_store: Optional[MetadataStore] = None,
                 vector_store: Optional[VectorStore] = None,
                 embedding_provider: Optional[EmbeddingProvider] = None,
                 chunker: Optional[Chunker] = None):

        self.config = get_config()
        self.metadata_store = metadata_store or MetadataStore()
        self.vector_store = vector_store or VectorStore()
        self.embedding_provider = embedding_provider or get_default_provider()
        self.chunker = chunker or Chunker()

    def memorize(self, content: str, tags: Optional[List[str]] = None,
                 source: Optional[str] = None,
                 heading_path: str = "Captured Knowledge") -> CaptureResult:
        """
        Capture knowledge into memory.

        Args:
            content: Text content to memorize
            tags: Optional list of tags
            source: Source description (e.g., "session:abc123", "conversation", "manual")
            heading_path: Logical heading path for organization

        Returns:
            CaptureResult with chunk IDs and status
        """
        if not content or not content.strip():
            return CaptureResult(
                success=False,
                chunk_ids=[],
                message="Empty content provided",
                chunk_count=0,
            )

        try:
            # Generate a virtual file path for tracking
            timestamp = int(time.time() * 1000)
            virtual_path = f"_captured/{source or 'manual'}/{timestamp}.md"

            # Chunk the content
            chunks = self._chunk_content(content, heading_path)

            if not chunks:
                return CaptureResult(
                    success=False,
                    chunk_ids=[],
                    message="No chunks generated from content",
                    chunk_count=0,
                )

            # Generate embeddings
            chunk_texts = [chunk.text for chunk in chunks]
            embedding_result = self.embedding_provider.generate_embeddings(chunk_texts)

            # Store chunks
            chunk_ids = []
            vector_ids = []
            embeddings = embedding_result.embeddings

            chunk_records = []
            for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
                vector_id = generate_chunk_id(virtual_path, i)
                chunk_ids.append(vector_id)
                vector_ids.append(vector_id)

                # Metadata store
                chunk_record = ChunkRecord(
                    id=vector_id,
                    file_path=virtual_path,
                    chunk_index=i,
                    heading_path=heading_path,
                    start_char=chunk.start_char,
                    end_char=chunk.end_char,
                    token_count=chunk.token_count,
                    chunk_hash=chunk.chunk_hash,
                    vector_id=vector_id,
                    created_at=int(time.time() * 1000),
                )
                chunk_records.append(chunk_record)

            self.metadata_store.batch_upsert_chunks(chunk_records)
            fts_entries = [(cr.id, chunk.text, heading_path, virtual_path)
                           for cr, chunk in zip(chunk_records, chunks)]
            self.metadata_store.batch_upsert_fts(fts_entries)

            # Vector store
            tag_str = ",".join(tags) if tags else ""
            metadatas = [{
                "file_path": virtual_path,
                "chunk_index": i,
                "heading_path": heading_path,
                "token_count": chunk.token_count,
                "tags": tag_str,
                "source": source or "manual",
                "captured_at": timestamp,
            } for i, chunk in enumerate(chunks)]

            self.vector_store.add(
                ids=vector_ids,
                embeddings=embeddings,
                metadatas=metadatas,
                documents=chunk_texts,
            )

            # Update file record for virtual file
            from memora.storage.metadata_store import FileRecord
            file_record = FileRecord(
                path=virtual_path,
                mtime=timestamp,
                size=len(content),
                frontmatter_hash=compute_hash(str({"tags": tags, "source": source})),
                content_hash=compute_hash(content),
                indexed_at=timestamp,
                status="indexed",
            )
            self.metadata_store.upsert_file(file_record)

            return CaptureResult(
                success=True,
                chunk_ids=chunk_ids,
                message=f"Captured {len(chunks)} chunks",
                chunk_count=len(chunks),
            )

        except Exception as e:
            return CaptureResult(
                success=False,
                chunk_ids=[],
                message=f"Capture failed: {e}",
                chunk_count=0,
            )

    def _chunk_content(self, content: str, heading_path: str) -> List[TextChunk]:
        """Chunk content using the configured chunker."""
        chunks = self.chunker.chunk_text(content, "_captured")

        # Update heading_path for all chunks
        for chunk in chunks:
            chunk.heading_path = heading_path

        return chunks

    def memorize_structured(self, title: str, content: str,
                           tags: Optional[List[str]] = None,
                           source: Optional[str] = None) -> CaptureResult:
        """
        Capture structured knowledge with title.

        Args:
            title: Title/heading for the knowledge
            content: Main content
            tags: Optional tags
            source: Source description

        Returns:
            CaptureResult
        """
        full_content = f"# {title}\n\n{content}"
        return self.memorize(full_content, tags, source, title)

    def capture_conversation(self, messages: List[Dict[str, str]],
                           tags: Optional[List[str]] = None,
                           session_id: Optional[str] = None) -> CaptureResult:
        """
        Capture a conversation (list of role/content messages).

        Args:
            messages: List of {"role": "user|assistant", "content": "..."}
            tags: Optional tags
            session_id: Session identifier

        Returns:
            CaptureResult
        """
        formatted = []
        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            formatted.append(f"**{role.capitalize()}**: {content}")

        full_content = "\n\n---\n\n".join(formatted)
        source = f"conversation:{session_id}" if session_id else "conversation"

        return self.memorize(full_content, tags, source, "Conversation")