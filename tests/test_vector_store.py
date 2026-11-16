"""
Tests for VectorStore.
"""

import pytest
from memora.storage.vector_store import VectorStore


class TestVectorStore:
    """Test VectorStore functionality."""

    def test_init_creates_collection(self, test_config, temp_dir):
        """Test initialization creates ChromaDB collection."""
        chroma_path = temp_dir / "chromadb"
        store = VectorStore(persist_path=str(chroma_path), collection_name="test_collection")

        info = store.get_collection_info()
        assert info["name"] == "test_collection"
        assert info["count"] == 0
        assert info["metadata"]["description"] == "MEMORA vault embeddings"

    def test_add_and_query(self, test_config, temp_dir):
        """Test adding vectors and querying."""
        chroma_path = temp_dir / "chromadb"
        store = VectorStore(persist_path=str(chroma_path), collection_name="test_add")

        ids = ["vec1", "vec2", "vec3"]
        embeddings = [
            [0.1] * 768,
            [0.2] * 768,
            [0.3] * 768,
        ]
        metadatas = [
            {"file_path": "a.md", "chunk_index": 0, "heading_path": "H1", "tags": "tag1"},
            {"file_path": "b.md", "chunk_index": 0, "heading_path": "H2", "tags": "tag2"},
            {"file_path": "a.md", "chunk_index": 1, "heading_path": "H1::H2", "tags": "tag1,tag3"},
        ]
        documents = [
            "Document about machine learning",
            "Document about web development",
            "Another document about machine learning",
        ]

        store.add(ids, embeddings, metadatas, documents)

        # Query with similar vector to first
        query_embedding = [[0.1] * 768]
        results = store.query(query_embedding, k=2)

        assert len(results["ids"][0]) == 2
        assert results["ids"][0][0] == "vec1"  # Most similar
        assert results["documents"][0][0] == "Document about machine learning"

    def test_add_with_metadata_filter(self, test_config, temp_dir):
        """Test querying with metadata filter."""
        chroma_path = temp_dir / "chromadb"
        store = VectorStore(persist_path=str(chroma_path), collection_name="test_filter")

        ids = ["vec1", "vec2", "vec3"]
        embeddings = [[0.1] * 768, [0.2] * 768, [0.3] * 768]
        metadatas = [
            {"file_path": "a.md", "chunk_index": 0},
            {"file_path": "b.md", "chunk_index": 0},
            {"file_path": "a.md", "chunk_index": 1},
        ]
        documents = ["Doc 1", "Doc 2", "Doc 3"]

        store.add(ids, embeddings, metadatas, documents)

        # Filter by file_path
        results = store.query(
            [[0.1] * 768],
            k=10,
            where={"file_path": "a.md"}
        )

        assert len(results["ids"][0]) == 2
        assert all(m["file_path"] == "a.md" for m in results["metadatas"][0])

    def test_get_by_ids(self, test_config, temp_dir):
        """Test retrieving vectors by ID."""
        chroma_path = temp_dir / "chromadb"
        store = VectorStore(persist_path=str(chroma_path), collection_name="test_get")

        ids = ["vec1", "vec2"]
        embeddings = [[0.1] * 768, [0.2] * 768]
        metadatas = [{"file_path": "a.md"}, {"file_path": "b.md"}]
        documents = ["Doc 1", "Doc 2"]

        store.add(ids, embeddings, metadatas, documents)

        results = store.get(["vec1"])
        assert len(results["ids"]) == 1
        assert results["ids"][0] == "vec1"
        assert results["documents"][0] == "Doc 1"
        # Compare embeddings element-wise
        assert all(abs(a - b) < 1e-6 for a, b in zip(results["embeddings"][0], [0.1] * 768))

    def test_delete_by_ids(self, test_config, temp_dir):
        """Test deleting vectors by ID."""
        chroma_path = temp_dir / "chromadb"
        store = VectorStore(persist_path=str(chroma_path), collection_name="test_delete")

        ids = ["vec1", "vec2", "vec3"]
        embeddings = [[0.1] * 768, [0.2] * 768, [0.3] * 768]
        metadatas = [{"file_path": "a.md"}, {"file_path": "b.md"}, {"file_path": "c.md"}]
        documents = ["Doc 1", "Doc 2", "Doc 3"]

        store.add(ids, embeddings, metadatas, documents)

        store.delete(["vec2"])
        results = store.get(["vec1", "vec2", "vec3"])

        assert len(results["ids"]) == 2
        assert "vec2" not in results["ids"]

    def test_delete_by_metadata(self, test_config, temp_dir):
        """Test deleting vectors by metadata filter."""
        chroma_path = temp_dir / "chromadb"
        store = VectorStore(persist_path=str(chroma_path), collection_name="test_delete_meta")

        ids = ["vec1", "vec2", "vec3"]
        embeddings = [[0.1] * 768, [0.2] * 768, [0.3] * 768]
        metadatas = [
            {"file_path": "a.md"},
            {"file_path": "a.md"},
            {"file_path": "b.md"},
        ]
        documents = ["Doc 1", "Doc 2", "Doc 3"]

        store.add(ids, embeddings, metadatas, documents)

        store.delete_by_metadata({"file_path": "a.md"})
        results = store.get(["vec1", "vec2", "vec3"])

        assert len(results["ids"]) == 1
        assert results["ids"][0] == "vec3"

    def test_count(self, test_config, temp_dir):
        """Test counting vectors."""
        chroma_path = temp_dir / "chromadb"
        store = VectorStore(persist_path=str(chroma_path), collection_name="test_count")

        assert store.count() == 0

        store.add(
            ["vec1", "vec2"],
            [[0.1] * 768, [0.2] * 768],
            [{"file_path": "a.md"}, {"file_path": "b.md"}],
            ["Doc 1", "Doc 2"]
        )

        assert store.count() == 2

    def test_peek(self, test_config, temp_dir):
        """Test peeking at first N vectors."""
        chroma_path = temp_dir / "chromadb"
        store = VectorStore(persist_path=str(chroma_path), collection_name="test_peek")

        store.add(
            ["vec1", "vec2", "vec3"],
            [[0.1] * 768, [0.2] * 768, [0.3] * 768],
            [{"file_path": "a.md"}, {"file_path": "b.md"}, {"file_path": "c.md"}],
            ["Doc 1", "Doc 2", "Doc 3"]
        )

        peeked = store.peek(limit=2)
        assert len(peeked["ids"]) == 2

    def test_update_metadata(self, test_config, temp_dir):
        """Test updating metadata for existing vectors."""
        chroma_path = temp_dir / "chromadb"
        store = VectorStore(persist_path=str(chroma_path), collection_name="test_update")

        store.add(
            ["vec1"],
            [[0.1] * 768],
            [{"file_path": "a.md", "tags": "old"}],
            ["Doc 1"]
        )

        store.update_metadata(["vec1"], [{"file_path": "a.md", "tags": "new"}])

        results = store.get(["vec1"])
        assert results["metadatas"][0]["tags"] == "new"

    def test_reset(self, test_config, temp_dir):
        """Test resetting collection."""
        chroma_path = temp_dir / "chromadb"
        store = VectorStore(persist_path=str(chroma_path), collection_name="test_reset")

        store.add(
            ["vec1", "vec2"],
            [[0.1] * 768, [0.2] * 768],
            [{"file_path": "a.md"}, {"file_path": "b.md"}],
            ["Doc 1", "Doc 2"]
        )

        assert store.count() == 2

        store.reset()
        assert store.count() == 0

        # Collection should be recreated with metadata
        info = store.get_collection_info()
        assert info["metadata"]["description"] == "MEMORA vault embeddings"

    def test_get_collection_info(self, test_config, temp_dir):
        """Test getting collection info."""
        chroma_path = temp_dir / "chromadb"
        store = VectorStore(persist_path=str(chroma_path), collection_name="test_info")

        info = store.get_collection_info()
        assert info["name"] == "test_info"
        assert "count" in info
        assert "metadata" in info
        assert "embedding_model" in info["metadata"]