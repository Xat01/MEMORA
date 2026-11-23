"""
MEMORA Memory Manager

High-level memory management combining capture, search, and context retrieval.
"""

from typing import Optional, List, Dict, Any

from memora.memory.capture import MemoryCapture, CaptureResult
from memora.retrieval.hybrid_search import HybridSearch, SearchResult
from memora.retrieval.keyword_search import KeywordSearch
from memora.retrieval.vector_search import VectorSearch
from memora.ingestion.indexer import Indexer
from memora.config import get_config


class MemoryManager:
    """
    Unified memory management interface.

    Provides:
    - memorize(): Capture knowledge
    - search(): Hybrid search
    - get_context(): Retrieve formatted context for a topic
    - list_sources(): Show indexed files
    - reindex(): Trigger full re-index
    - status(): Get index statistics
    """

    def __init__(self,
                 indexer: Optional[Indexer] = None,
                 hybrid_search: Optional[HybridSearch] = None,
                 memory_capture: Optional[MemoryCapture] = None):

        self.config = get_config()
        self.indexer = indexer or Indexer()
        self.hybrid_search = hybrid_search or HybridSearch()
        self.memory_capture = memory_capture or MemoryCapture()

    def memorize(self, content: str, tags: Optional[List[str]] = None,
                 source: Optional[str] = None) -> CaptureResult:
        """
        Capture knowledge into memory.

        Args:
            content: Text to memorize
            tags: Optional tags
            source: Source description

        Returns:
            CaptureResult
        """
        return self.memory_capture.memorize(content, tags, source)

    def search(self, query: str, k: int = 10,
               mode: str = "hybrid",
               file_paths: Optional[List[str]] = None,
               tags: Optional[List[str]] = None) -> List[SearchResult]:
        """
        Search memory.

        Args:
            query: Search query
            k: Number of results
            mode: "hybrid", "keyword", or "vector"
            file_paths: Optional file path filter
            tags: Optional tag filter

        Returns:
            List of SearchResult
        """
        return self.hybrid_search.search(query, k, mode, file_paths, tags)

    def get_context(self, topic: str, k: int = 5,
                   mode: str = "hybrid",
                   max_chars: int = 3000) -> Dict[str, Any]:
        """
        Get relevant context for a topic, formatted for LLM consumption.

        Args:
            topic: Topic to retrieve context for
            k: Number of chunks to retrieve
            mode: Search mode
            max_chars: Maximum total characters in context

        Returns:
            Dict with context string and metadata
        """
        results = self.search(topic, k, mode)

        if not results:
            return {
                "context": "",
                "chunks": [],
                "total_chars": 0,
                "message": "No relevant context found",
            }

        # Build context string
        context_parts = []
        total_chars = 0
        chunks_used = []

        for i, result in enumerate(results):
            chunk_text = result.content
            header = f"[Source {i+1}: {result.file_path}"
            if result.heading_path:
                header += f" > {result.heading_path}"
            header += f" (similarity: {result.rrf_score:.3f})]"

            chunk_with_header = f"{header}\n{chunk_text}"

            if total_chars + len(chunk_with_header) > max_chars:
                # Truncate last chunk to fit
                remaining = max_chars - total_chars
                if remaining > 100:
                    chunk_with_header = chunk_with_header[:remaining] + "... [truncated]"
                    context_parts.append(chunk_with_header)
                    chunks_used.append(result)
                break

            context_parts.append(chunk_with_header)
            total_chars += len(chunk_with_header)
            chunks_used.append(result)

        context = "\n\n---\n\n".join(context_parts)

        return {
            "context": context,
            "chunks": [r.to_dict() for r in chunks_used],
            "total_chars": total_chars,
            "chunk_count": len(chunks_used),
            "message": f"Retrieved {len(chunks_used)} relevant chunks",
        }

    def list_sources(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        List indexed source files.

        Args:
            limit: Maximum sources to return (None for all sources)

        Returns:
            List of file info dicts
        """
        stats = self.indexer.metadata_store.get_index_stats()
        files = self.indexer.metadata_store.get_all_files()

        # Sort by indexed_at descending
        files.sort(key=lambda f: f.indexed_at, reverse=True)

        selected_files = files if limit is None else files[:limit]
        sources = []
        for f in selected_files:
            chunks = self.indexer.metadata_store.get_chunks_by_file(f.path)
            sources.append({
                "path": f.path,
                "status": f.status,
                "size": f.size,
                "chunk_count": len(chunks),
                "indexed_at": f.indexed_at,
                "mtime": f.mtime,
            })

        return sources

    def reindex(self, full: bool = False) -> Dict[str, Any]:
        """
        Trigger re-indexing of the vault.

        Args:
            full: If True, full re-index ignoring change detection

        Returns:
            Dict with indexing statistics
        """
        stats = self.indexer.index(full_reindex=full)

        return {
            "files_processed": stats.files_processed,
            "files_indexed": stats.files_indexed,
            "files_skipped": stats.files_skipped,
            "files_deleted": stats.files_deleted,
            "chunks_created": stats.chunks_created,
            "chunks_deleted": stats.chunks_deleted,
            "duration_seconds": stats.duration_seconds,
            "errors": stats.errors,
        }

    def status(self) -> Dict[str, Any]:
        """Get comprehensive memory status."""
        index_stats = self.indexer.get_status()
        vector_info = self.indexer.vector_store.get_collection_info()

        return {
            "index": index_stats,
            "vector_store": vector_info,
            "config": {
                "embedding_model": self.config.embedding_model,
                "embedding_dimensions": self.config.embedding_dimensions,
                "chunk_size": self.config.chunk_size,
                "chunk_overlap": self.config.chunk_overlap,
                "vault_path": str(self.config.vault_path),
            },
        }

    def get_chunk(self, chunk_id: str) -> Optional[SearchResult]:
        """Get a specific chunk by ID."""
        return self.hybrid_search.get_chunk_by_id(chunk_id)

    def find_similar(self, chunk_id: str, k: int = 5) -> List[SearchResult]:
        """Find chunks similar to a given chunk."""
        vec_results = self.hybrid_search.vector_search.get_similar_chunks(chunk_id, k)

        results = []
        for vr in vec_results:
            tag_list = [t.strip() for t in vr.tags.split(",")] if vr.tags else []
            results.append(SearchResult(
                chunk_id=vr.chunk_id,
                content=vr.content,
                file_path=vr.file_path,
                chunk_index=vr.chunk_index,
                heading_path=vr.heading_path,
                tags=tag_list,
                vector_rank=vr.vector_rank,
                vector_score=vr.similarity,
                rrf_score=vr.similarity,
                source="similarity",
            ))
        return results