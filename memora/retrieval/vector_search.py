"""
MEMORA Vector Search

Semantic similarity search using ChromaDB embeddings.
"""

from dataclasses import dataclass
from typing import Optional, List

from memora.embeddings.base import EmbeddingProvider
from memora.embeddings.ollama_provider import OllamaProvider
from memora.storage.vector_store import VectorStore
from memora.config import get_config


@dataclass
class VectorResult:
    """Result from vector search."""
    chunk_id: str
    content: str
    file_path: str
    chunk_index: int
    heading_path: str
    tags: str
    distance: float        # Cosine distance (0=identical, 2=opposite)
    similarity: float      # Cosine similarity (1=identical, 0=orthogonal, -1=opposite)
    score: float           # Normalized score (0-1, higher is better)


class VectorSearch:
    """
    Semantic vector search using ChromaDB.
    """

    def __init__(self,
                 vector_store: Optional[VectorStore] = None,
                 embedding_provider: Optional[EmbeddingProvider] = None):
        self.vector_store = vector_store or VectorStore()
        # Use OllamaProvider if available, otherwise require explicit provider
        if embedding_provider is None:
            try:
                ollama = OllamaProvider()
                if ollama.health_check():
                    self.embedding_provider = ollama
                else:
                    raise Exception("Ollama not healthy")
            except Exception:
                # Will raise error on first use if no provider available
                self.embedding_provider = None
        else:
            self.embedding_provider = embedding_provider

    def search(self, query: str, k: int = 10,
               file_paths: Optional[List[str]] = None,
               tags: Optional[List[str]] = None) -> List[VectorResult]:
        """
        Search for semantically similar chunks.

        Args:
            query: Natural language search query
            k: Maximum number of results
            file_paths: Optional list of file paths to filter
            tags: Optional list of tags to filter (comma-separated in metadata)

        Returns:
            List of VectorResult sorted by similarity (highest first)
        """
        if self.embedding_provider is None:
            raise RuntimeError("No embedding provider available. Ollama not running or not configured.")

        # Generate query embedding
        result = self.embedding_provider.generate_embeddings([query])
        query_embedding = result.embeddings[0]

        # Build metadata filter
        query_kwargs = {
            "query_embeddings": [query_embedding],
            "k": k * 2 if (file_paths or tags) else k,
        }
        if file_paths:
            query_kwargs["where"] = {"file_path": {"$in": file_paths}}

        # Execute search
        raw_results = self.vector_store.query(**query_kwargs)

        # Format results
        results = []
        if raw_results.get("ids") and raw_results["ids"][0]:
            for i, chunk_id in enumerate(raw_results["ids"][0]):
                metadata = raw_results["metadatas"][0][i]
                distance = raw_results["distances"][0][i]
                similarity = 1.0 - distance  # Cosine similarity

                # Post-filter by tags if needed
                if tags:
                    chunk_tags = metadata.get("tags", "").split(",")
                    if not any(t in chunk_tags for t in tags):
                        continue

                results.append(VectorResult(
                    chunk_id=chunk_id,
                    content=raw_results["documents"][0][i],
                    file_path=metadata.get("file_path", ""),
                    chunk_index=metadata.get("chunk_index", 0),
                    heading_path=metadata.get("heading_path", ""),
                    tags=metadata.get("tags", ""),
                    distance=distance,
                    similarity=similarity,
                    score=similarity,  # Already 0-1 for cosine
                ))

        # Sort by similarity descending
        results.sort(key=lambda r: r.similarity, reverse=True)

        return results[:k]

    def search_by_embedding(self, embedding: List[float], k: int = 10,
                           file_paths: Optional[List[str]] = None) -> List[VectorResult]:
        """
        Search using a pre-computed embedding.

        Args:
            embedding: Pre-computed query embedding
            k: Maximum number of results
            file_paths: Optional file path filter

        Returns:
            List of VectorResult
        """
        where = None
        if file_paths:
            where = {"file_path": {"$in": file_paths}}

        raw_results = self.vector_store.query(
            query_embeddings=[embedding],
            k=k,
            where=where,
        )

        results = []
        if raw_results.get("ids") and raw_results["ids"][0]:
            for i, chunk_id in enumerate(raw_results["ids"][0]):
                metadata = raw_results["metadatas"][0][i]
                distance = raw_results["distances"][0][i]
                similarity = 1.0 - distance

                results.append(VectorResult(
                    chunk_id=chunk_id,
                    content=raw_results["documents"][0][i],
                    file_path=metadata.get("file_path", ""),
                    chunk_index=metadata.get("chunk_index", 0),
                    heading_path=metadata.get("heading_path", ""),
                    tags=metadata.get("tags", ""),
                    distance=distance,
                    similarity=similarity,
                    score=similarity,
                ))

        results.sort(key=lambda r: r.similarity, reverse=True)
        return results[:k]

    def get_similar_chunks(self, chunk_id: str, k: int = 5) -> List[VectorResult]:
        """
        Find chunks similar to a given chunk.

        Args:
            chunk_id: Reference chunk ID
            k: Number of similar chunks to return

        Returns:
            List of VectorResult (excluding the reference chunk)
        """
        # Get the chunk's embedding
        chunk_data = self.vector_store.get([chunk_id])

        if not chunk_data.get("embeddings") or not chunk_data["embeddings"]:
            return []

        embedding = chunk_data["embeddings"][0]

        # Search for similar
        results = self.search_by_embedding(embedding, k=k+1)

        # Filter out the reference chunk
        return [r for r in results if r.chunk_id != chunk_id][:k]