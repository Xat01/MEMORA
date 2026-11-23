"""
MEMORA Indexer

Coordinates the ingestion pipeline: vault reading -> chunking -> embedding -> storage.
Handles incremental indexing with change detection.
"""

import time
from dataclasses import dataclass
from typing import Optional, Callable

from memora.config import get_config
from memora.ingestion.vault_reader import VaultReader, VaultFile
from memora.ingestion.chunker import Chunker, TextChunk, chunk_vault_file
from memora.embeddings.base import EmbeddingProvider
from memora.embeddings import get_default_provider
from memora.storage.metadata_store import MetadataStore, FileRecord, ChunkRecord, compute_hash, generate_chunk_id
from memora.storage.vector_store import VectorStore


@dataclass
class IndexStats:
    """Statistics from an indexing run."""
    files_processed: int = 0
    files_indexed: int = 0
    files_skipped: int = 0
    files_deleted: int = 0
    chunks_created: int = 0
    chunks_updated: int = 0
    chunks_deleted: int = 0
    embeddings_generated: int = 0
    errors: list[str] = None
    duration_seconds: float = 0.0

    def __post_init__(self):
        if self.errors is None:
            self.errors = []


class Indexer:
    """
    Main indexing coordinator.

    Pipeline:
    1. Scan vault for files
    2. Detect changes (new, modified, deleted)
    3. Process changed files: read -> chunk -> embed -> store
    4. Update metadata store and vector store
    5. Track statistics
    """

    def __init__(self,
                 metadata_store: Optional[MetadataStore] = None,
                 vector_store: Optional[VectorStore] = None,
                 embedding_provider: Optional[EmbeddingProvider] = None,
                 vault_reader: Optional[VaultReader] = None,
                 chunker: Optional[Chunker] = None,
                 progress_callback: Optional[Callable[[str, int, int], None]] = None):

        try:
            self.config = get_config()
        except Exception:
            self.config = None

        # Initialize components
        self.metadata_store = metadata_store or MetadataStore()
        self.vector_store = vector_store or VectorStore()
        self.embedding_provider = embedding_provider or get_default_provider()
        self.vault_reader = vault_reader or VaultReader()
        self.chunker = chunker or Chunker()

        # Progress callback: callback(message, current, total)
        self.progress_callback = progress_callback

        # Ensure embedding model matches stored config
        self._verify_embedding_config()

    def _verify_embedding_config(self) -> None:
        """Verify embedding model matches stored configuration."""
        stored_model = self.metadata_store.get_meta("embedding_model")
        stored_dims = self.metadata_store.get_meta("embedding_dimensions")

        # Get current model from config or embedding provider
        if self.config:
            current_model = self.config.embedding_model
            current_dims = str(self.config.embedding_dimensions)
        else:
            current_model = self.embedding_provider.model_name
            current_dims = str(self.embedding_provider.dimensions)

        if stored_model and stored_model != current_model:
            print(f"WARNING: Embedding model changed from '{stored_model}' to '{current_model}'")
            print("Consider re-indexing for consistency.")

        if stored_dims and stored_dims != current_dims:
            print(f"WARNING: Embedding dimensions changed from {stored_dims} to {current_dims}")
            print("Consider re-indexing for consistency.")

        # Update stored config
        self.metadata_store.set_meta("embedding_model", current_model)
        self.metadata_store.set_meta("embedding_dimensions", current_dims)

    def index(self, full_reindex: bool = False) -> IndexStats:
        """
        Run indexing pipeline.

        Args:
            full_reindex: If True, ignore change detection and re-index all files

        Returns:
            IndexStats with results
        """
        start_time = time.time()
        stats = IndexStats()

        try:
            # Step 1: Get all vault files
            self._report_progress("Scanning vault...", 0, 1)
            vault_files = self._get_vault_files()
            stats.files_processed = len(vault_files)

            # Step 2: Detect changes
            self._report_progress("Detecting changes...", 0, 1)
            to_index, to_delete = self._detect_changes(vault_files, full_reindex)

            # Track skipped files (unchanged)
            stats.files_skipped = len(vault_files) - len(to_index) - len([p for p in vault_files if p.path in [d for d in to_delete]])

            # Step 3: Process deletions
            if to_delete:
                self._report_progress(f"Processing {len(to_delete)} deletions...", 0, len(to_delete))
                for i, path in enumerate(to_delete):
                    chunks = self.metadata_store.get_chunks_by_file(path)
                    self._delete_file(path)
                    stats.files_deleted += 1
                    stats.chunks_deleted += len(chunks)
                    self._report_progress(f"Deleted {path}", i + 1, len(to_delete))

            # Step 4: Process new/modified files
            if to_index:
                self._report_progress(f"Indexing {len(to_index)} files...", 0, len(to_index))
                for i, vault_file in enumerate(to_index):
                    try:
                        num_chunks = self._index_file(vault_file)
                        stats.files_indexed += 1
                        stats.chunks_created += num_chunks
                        stats.embeddings_generated += num_chunks
                    except Exception as e:
                        error_msg = f"Error indexing {vault_file.path}: {e}"
                        stats.errors.append(error_msg)
                        print(f"ERROR: {error_msg}")

                    self._report_progress(f"Indexed {vault_file.path}", i + 1, len(to_index))

            # Step 5: Update index metadata
            self.metadata_store.set_meta("last_indexed", str(int(time.time())))
            self.metadata_store.set_meta("last_indexed_iso", time.strftime("%Y-%m-%dT%H:%M:%S"))

            stats.duration_seconds = time.time() - start_time
            self._report_progress("Indexing complete", 1, 1)

            return stats

        except Exception as e:
            stats.errors.append(f"Indexing failed: {e}")
            stats.duration_seconds = time.time() - start_time
            return stats

    def _get_vault_files(self) -> list[VaultFile]:
        """Get all markdown files from vault."""
        paths = self.vault_reader.list_files([".md"])
        files = []
        for path in paths:
            vf = self.vault_reader.read_file(path)
            if vf:
                files.append(vf)
        return files

    def _detect_changes(self, vault_files: list[VaultFile],
                       full_reindex: bool) -> tuple[list[VaultFile], list[str]]:
        """
        Detect which files need indexing and which were deleted.

        Returns:
            (files_to_index, deleted_file_paths)
        """
        to_index = []
        vault_paths = {vf.path for vf in vault_files}

        # Check each vault file
        for vf in vault_files:
            if full_reindex:
                to_index.append(vf)
                continue

            existing = self.metadata_store.get_file(vf.path)

            if existing is None:
                # New file
                to_index.append(vf)
            elif existing.status == "deleted":
                # Was deleted, now back
                to_index.append(vf)
            else:
                # Check if modified
                content_hash = compute_hash(vf.content_without_frontmatter)
                frontmatter_hash = compute_hash(str(vf.frontmatter))

                if (existing.content_hash != content_hash or
                    existing.frontmatter_hash != frontmatter_hash or
                    existing.mtime != vf.mtime):
                    to_index.append(vf)

        # Find deleted files (in metadata but not in vault)
        to_delete = []
        if not full_reindex:
            all_tracked = self.metadata_store.get_all_files()
            for tracked in all_tracked:
                if tracked.path not in vault_paths and tracked.status != "deleted":
                    to_delete.append(tracked.path)

        return to_index, to_delete

    def _index_file(self, vault_file: VaultFile) -> int:
        """Index a single vault file. Returns chunk count."""
        # Chunk the file
        chunks = chunk_vault_file(vault_file, self.chunker)

        # Clean up existing chunks for this file if updating
        old_chunks = self.metadata_store.get_chunks_by_file(vault_file.path)
        if old_chunks:
            old_ids = [c.vector_id for c in old_chunks]
            try:
                self.vector_store.delete(old_ids)
            except Exception:
                pass
            self.metadata_store.delete_chunks_by_file(vault_file.path)

        if not chunks:
            # Empty file - still track it
            self._update_file_record(vault_file, [])
            return 0

        # Generate embeddings in batch
        chunk_texts = [chunk.text for chunk in chunks]
        embedding_result = self.embedding_provider.generate_embeddings(chunk_texts)

        # Store in metadata and vector stores
        chunk_records = []
        vector_ids = []
        embeddings = embedding_result.embeddings

        for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
            vector_id = generate_chunk_id(vault_file.path, i)
            vector_ids.append(vector_id)

            # Metadata store record
            chunk_record = ChunkRecord(
                id=vector_id,
                file_path=vault_file.path,
                chunk_index=i,
                heading_path=chunk.heading_path,
                start_char=chunk.start_char,
                end_char=chunk.end_char,
                token_count=chunk.token_count,
                chunk_hash=chunk.chunk_hash,
                vector_id=vector_id,
                created_at=int(time.time() * 1000),
            )
            chunk_records.append(chunk_record)

        # Batch write chunks to metadata store in a single transaction
        self.metadata_store.batch_upsert_chunks(chunk_records)

        # Batch write FTS5 entries in a single transaction
        fts_entries = [
            (cr.id, chunk.text, chunk.heading_path, vault_file.path)
            for cr, chunk in zip(chunk_records, chunks)
        ]
        self.metadata_store.batch_upsert_fts(fts_entries)

        # Batch add to vector store
        metadatas = [{
            "file_path": vault_file.path,
            "chunk_index": i,
            "heading_path": chunk.heading_path,
            "token_count": chunk.token_count,
            "tags": ",".join(vault_file.tags),
        } for i, chunk in enumerate(chunks)]

        self.vector_store.add(
            ids=vector_ids,
            embeddings=embeddings,
            metadatas=metadatas,
            documents=chunk_texts,
        )

        # Update file record
        self._update_file_record(vault_file, chunk_records)
        return len(chunk_records)

    def _update_file_record(self, vault_file: VaultFile, chunks: list[ChunkRecord]) -> None:
        """Update file record in metadata store."""
        content_hash = compute_hash(vault_file.content_without_frontmatter)
        frontmatter_hash = compute_hash(str(vault_file.frontmatter))

        record = FileRecord(
            path=vault_file.path,
            mtime=vault_file.mtime,
            size=vault_file.size,
            frontmatter_hash=frontmatter_hash,
            content_hash=content_hash,
            indexed_at=int(time.time() * 1000),
            status="indexed",
        )
        self.metadata_store.upsert_file(record)

    def _delete_file(self, path: str) -> None:
        """Delete a file from all stores."""
        # Get chunks to delete from vector store
        chunks = self.metadata_store.get_chunks_by_file(path)
        vector_ids = [c.vector_id for c in chunks]

        # Delete from vector store
        if vector_ids:
            self.vector_store.delete(vector_ids)

        # Delete from metadata store
        self.metadata_store.delete_chunks_by_file(path)
        self.metadata_store.delete_file_record(path)

    def _report_progress(self, message: str, current: int, total: int) -> None:
        """Report progress via callback."""
        if self.progress_callback:
            self.progress_callback(message, current, total)

    # =========================================================================
    # Utility Methods
    # =========================================================================

    def get_status(self) -> dict:
        """Get current index status."""
        stats = self.metadata_store.get_index_stats()
        stats["vector_count"] = self.vector_store.count()
        return stats

    def search_keyword(self, query: str, k: int = 10) -> list[dict]:
        """Keyword search via metadata store."""
        return self.metadata_store.keyword_search(query, k)

    def search_vector(self, query: str, k: int = 10,
                     embedding_provider: Optional[EmbeddingProvider] = None) -> list[dict]:
        """Vector search via vector store."""
        provider = embedding_provider or self.embedding_provider
        result = provider.generate_embeddings([query])
        query_embedding = result.embeddings[0]

        results = self.vector_store.query([query_embedding], k=k)

        # Format results
        formatted = []
        if results.get("ids") and results["ids"][0]:
            for i, chunk_id in enumerate(results["ids"][0]):
                formatted.append({
                    "chunk_id": chunk_id,
                    "content": results["documents"][0][i],
                    "metadata": results["metadatas"][0][i],
                    "distance": results["distances"][0][i],
                    "similarity": 1 - results["distances"][0][i],
                })
        return formatted

    def reindex_file(self, path: str) -> bool:
        """Force re-index a specific file."""
        vault_file = self.vault_reader.read_file(path)
        if vault_file:
            self._index_file(vault_file)
            return True
        return False


def create_indexer(progress_callback: Optional[Callable[[str, int, int], None]] = None) -> Indexer:
    """Factory function to create a fully configured Indexer."""
    from memora.config import get_config
    config = get_config()
    metadata_store = MetadataStore(db_path=config.sqlite_path)
    vector_store = VectorStore(persist_path=str(config.chroma_path))
    return Indexer(
        metadata_store=metadata_store,
        vector_store=vector_store,
        progress_callback=progress_callback,
    )