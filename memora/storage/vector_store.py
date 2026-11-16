"""
MEMORA Vector Store

ChromaDB-based persistent vector storage for semantic embeddings.
"""

from typing import Optional
import chromadb
from chromadb.config import Settings as ChromaSettings

from memora.config import get_config


class VectorStore:
    """
    ChromaDB vector store for semantic search.

    Stores embeddings with metadata for filtering and retrieval.
    """

    def __init__(self, persist_path: Optional[str] = None,
                 collection_name: str = "memora_vault"):
        if persist_path is None:
            try:
                self.config = get_config()
                self.persist_path = str(self.config.chroma_path)
            except Exception:
                self.config = None
                self.persist_path = "./data/chromadb"
        else:
            self.config = None
            self.persist_path = persist_path
        self.collection_name = collection_name
        self._client: Optional[chromadb.PersistentClient] = None
        self._collection = None

    @property
    def client(self) -> chromadb.PersistentClient:
        """Get or create ChromaDB client."""
        if self._client is None:
            self._client = chromadb.PersistentClient(
                path=self.persist_path,
                settings=ChromaSettings(
                    anonymized_telemetry=False,
                    allow_reset=True,
                )
            )
        return self._client

    @property
    def collection(self):
        """Get or create collection."""
        if self._collection is None:
            embedding_model = self.config.embedding_model if self.config else "nomic-embed-text"
            embedding_dimensions = self.config.embedding_dimensions if self.config else 768
            self._collection = self.client.get_or_create_collection(
                name=self.collection_name,
                metadata={
                    "description": "MEMORA vault embeddings",
                    "embedding_model": embedding_model,
                    "embedding_dimensions": str(embedding_dimensions),
                }
            )
        return self._collection

    def add(self, ids: list[str], embeddings: list[list[float]],
            metadatas: list[dict], documents: list[str]) -> None:
        """
        Add embeddings to the collection.

        Args:
            ids: Unique identifiers for each embedding
            embeddings: List of embedding vectors
            metadatas: List of metadata dicts (must include file_path, chunk_index, etc.)
            documents: List of original text chunks
        """
        self.collection.add(
            ids=ids,
            embeddings=embeddings,
            metadatas=metadatas,
            documents=documents,
        )

    def query(self, query_embeddings: list[list[float]], k: int = 10,
              where: Optional[dict] = None,
              where_document: Optional[dict] = None) -> dict:
        """
        Query similar vectors.

        Args:
            query_embeddings: List of query embedding vectors
            k: Number of results
            where: Metadata filter (e.g., {"file_path": "path/to/file.md"})
            where_document: Document content filter

        Returns:
            Dict with ids, distances, metadatas, documents
        """
        query_args = {
            "query_embeddings": query_embeddings,
            "n_results": k,
            "include": ["metadatas", "documents", "distances"],
        }
        if where is not None:
            query_args["where"] = where
        if where_document is not None:
            query_args["where_document"] = where_document
        return self.collection.query(**query_args)

    def get(self, ids: list[str]) -> dict:
        """Get specific vectors by IDs."""
        return self.collection.get(
            ids=ids,
            include=["metadatas", "documents", "embeddings"],
        )

    def delete(self, ids: list[str]) -> None:
        """Delete vectors by IDs."""
        self.collection.delete(ids=ids)

    def delete_by_metadata(self, where: dict) -> None:
        """Delete vectors matching metadata filter."""
        self.collection.delete(where=where)

    def count(self) -> int:
        """Get total number of vectors in collection."""
        return self.collection.count()

    def peek(self, limit: int = 10) -> dict:
        """Peek at first N vectors."""
        return self.collection.peek(limit=limit)

    def update_metadata(self, ids: list[str], metadatas: list[dict]) -> None:
        """Update metadata for existing vectors."""
        self.collection.update(ids=ids, metadatas=metadatas)

    def reset(self) -> None:
        """Reset the entire collection (delete all)."""
        self.client.delete_collection(name=self.collection_name)
        self._collection = None
        # Recreate
        embedding_model = self.config.embedding_model if self.config else "nomic-embed-text"
        embedding_dimensions = self.config.embedding_dimensions if self.config else 768
        self._collection = self.client.get_or_create_collection(
            name=self.collection_name,
            metadata={
                "description": "MEMORA vault embeddings",
                "embedding_model": embedding_model,
                "embedding_dimensions": str(embedding_dimensions),
            }
        )

    def get_collection_info(self) -> dict:
        """Get collection metadata and stats."""
        return {
            "name": self.collection_name,
            "count": self.count(),
            "metadata": self.collection.metadata,
        }