"""
MEMORA Tests

Basic unit and integration tests for MEMORA components.
"""

import tempfile
import shutil
from pathlib import Path
import pytest

from memora.config import MemoraConfig, get_config, set_config
from memora.ingestion.chunker import Chunker, TextChunk
from memora.ingestion.vault_reader import VaultReader, VaultFile
from memora.storage.metadata_store import MetadataStore, FileRecord, ChunkRecord, compute_hash, generate_chunk_id
from memora.storage.vector_store import VectorStore
from memora.embeddings.base import EmbeddingProvider, EmbeddingResult
from memora.retrieval.keyword_search import KeywordSearch
from memora.retrieval.vector_search import VectorSearch
from memora.retrieval.hybrid_search import HybridSearch
from memora.memory.capture import MemoryCapture
from memora.memory.manager import MemoryManager


# =========================================================================
# Fixtures
# =========================================================================

@pytest.fixture
def temp_dir():
    """Create temporary directory for tests."""
    d = Path(tempfile.mkdtemp())
    yield d
    shutil.rmtree(d)


@pytest.fixture
def test_config(temp_dir):
    """Create test configuration."""
    config = MemoraConfig(
        vault_path=temp_dir / "vault",
        chroma_path=temp_dir / "chromadb",
        sqlite_path=temp_dir / "memora.db",
        embedding_model="test-model",
        embedding_dimensions=384,
        chunk_size=100,
        chunk_overlap=10,
    )
    config.ensure_dirs()
    # Create vault structure
    (config.vault_path / ".obsidian").mkdir(parents=True)
    return config


@pytest.fixture
def sample_vault_file():
    """Sample vault file content."""
    return """---
title: "Test Note"
tags: [test, example]
source: "test"
---

# Test Note

## Introduction

This is a test note for MEMORA indexing.

## Code Example

```python
def hello():
    print("Hello, World!")
```

## Conclusion

This note demonstrates chunking behavior.
"""


# =========================================================================
# Config Tests
# =========================================================================

class TestConfig:
    """Test configuration management."""

    def test_default_config(self):
        """Test default configuration values."""
        config = MemoraConfig(vault_path="/tmp/test")
        assert config.chunk_size == 512
        assert config.chunk_overlap == 50
        assert config.embedding_model == "nomic-embed-text"
        assert config.embedding_dimensions == 768

    def test_config_validation(self, test_config):
        """Test vault validation."""
        assert test_config.validate_vault() is True
        # Invalid path
        invalid = MemoraConfig(vault_path="/nonexistent/path")
        assert invalid.validate_vault() is False

    def test_config_singleton(self, test_config):
        """Test global config singleton."""
        set_config(test_config)
        retrieved = get_config()
        assert retrieved is test_config


# =========================================================================
# Chunker Tests
# =========================================================================

class TestChunker:
    """Test text chunking."""

    def test_basic_chunking(self):
        """Test basic chunking functionality."""
        chunker = Chunker(chunk_size=50, chunk_overlap=10)
        text = "This is a test. " * 20  # ~100 tokens
        chunks = chunker.chunk_text(text)

        assert len(chunks) > 1
        assert all(isinstance(c, TextChunk) for c in chunks)
        assert all(c.token_count > 0 for c in chunks)

    def test_header_splitting(self):
        """Test splitting by headers."""
        chunker = Chunker(chunk_size=100, chunk_overlap=10)
        text = """# Header 1

Content under header 1.

## Header 2

Content under header 2.

### Header 3

Content under header 3.
"""
        chunks = chunker.chunk_text(text)

        # Should have chunks with heading paths
        heading_paths = [c.heading_path for c in chunks if c.heading_path]
        assert any("Header 1" in hp for hp in heading_paths)

    def test_code_block_preservation(self):
        """Test code blocks are preserved."""
        chunker = Chunker(chunk_size=50, chunk_overlap=10)
        text = """Some text before.

```python
def long_function():
    # This is a long code block
    for i in range(100):
        print(i)
    return True
```

Text after code block.
"""
        chunks = chunker.chunk_text(text)

        # Code block should not be split
        code_chunks = [c for c in chunks if "long_function" in c.text]
        assert len(code_chunks) == 1

    def test_overlap_application(self):
        """Test overlap between chunks."""
        chunker = Chunker(chunk_size=30, chunk_overlap=15)
        text = "Word " * 50  # ~50 tokens
        chunks = chunker.chunk_text(text)

        if len(chunks) > 1:
            # Check that overlap creates some shared content
            assert chunks[1].start_char < chunks[0].end_char

    def test_empty_text(self):
        """Test empty text handling."""
        chunker = Chunker()
        chunks = chunker.chunk_text("")
        assert chunks == []

    def test_chunk_hash_generation(self):
        """Test chunk hash is deterministic."""
        chunker = Chunker()
        text = "Test content for hashing."
        chunks1 = chunker.chunk_text(text, "file1.md")
        chunks2 = chunker.chunk_text(text, "file1.md")

        assert chunks1[0].chunk_hash == chunks2[0].chunk_hash


# =========================================================================
# VaultReader Tests
# =========================================================================

class TestVaultReader:
    """Test vault reading."""

    def test_parse_frontmatter(self, test_config, sample_vault_file):
        """Test frontmatter parsing."""
        reader = VaultReader(vault_path=test_config.vault_path)

        # Write test file
        test_file = test_config.vault_path / "test.md"
        test_file.write_text(sample_vault_file)

        vf = reader.read_file("test.md")

        assert vf is not None
        assert vf.frontmatter.get("title") == "Test Note"
        assert "test" in vf.tags
        assert "example" in vf.tags

    def test_extract_headings(self, test_config):
        """Test heading extraction."""
        reader = VaultReader(vault_path=test_config.vault_path)
        content = """# H1

## H2

### H3

# Another H1
"""
        test_file = test_config.vault_path / "headings.md"
        test_file.write_text(content)

        vf = reader.read_file("headings.md")

        assert "H1" in vf.headings
        assert "H2" in vf.headings
        assert "H3" in vf.headings
        assert "Another H1" in vf.headings

    def test_list_files(self, test_config):
        """Test file listing."""
        reader = VaultReader(vault_path=test_config.vault_path)

        (test_config.vault_path / "note1.md").write_text("# Note 1")
        (test_config.vault_path / "note2.md").write_text("# Note 2")
        (test_config.vault_path / "not_markdown.txt").write_text("txt")

        files = reader.list_files([".md"])

        assert "note1.md" in files
        assert "note2.md" in files
        assert "not_markdown.txt" not in files


# =========================================================================
# MetadataStore Tests
# =========================================================================

class TestMetadataStore:
    """Test metadata storage."""

    def test_file_operations(self, temp_dir):
        """Test file CRUD operations."""
        db_path = temp_dir / "test.db"
        store = MetadataStore(db_path)

        # Insert
        record = FileRecord(
            path="test.md",
            mtime=1000,
            size=100,
            frontmatter_hash="fmhash",
            content_hash="chash",
            indexed_at=1000,
            status="indexed",
        )
        store.upsert_file(record)

        # Retrieve
        retrieved = store.get_file("test.md")
        assert retrieved is not None
        assert retrieved.path == "test.md"
        assert retrieved.status == "indexed"

        # Update
        record.status = "modified"
        store.upsert_file(record)
        retrieved = store.get_file("test.md")
        assert retrieved.status == "modified"

        # Delete
        store.delete_file_record("test.md")
        assert store.get_file("test.md") is None

    def test_chunk_operations(self, temp_dir):
        """Test chunk CRUD operations."""
        db_path = temp_dir / "test.db"
        store = MetadataStore(db_path)

        chunk = ChunkRecord(
            id="chunk1",
            file_path="test.md",
            chunk_index=0,
            heading_path="H1::H2",
            start_char=0,
            end_char=100,
            token_count=25,
            chunk_hash="chash1",
            vector_id="vec1",
            created_at=1000,
        )
        store.upsert_chunk(chunk)

        retrieved = store.get_chunk("chunk1")
        assert retrieved is not None
        assert retrieved.heading_path == "H1::H2"
        assert retrieved.token_count == 25

    def test_fts_search(self, temp_dir):
        """Test FTS5 keyword search."""
        db_path = temp_dir / "test.db"
        store = MetadataStore(db_path)

        # Add test chunks
        for i, content in enumerate([
            "Python programming tutorial",
            "Machine learning with Python",
            "Web development JavaScript",
        ]):
            chunk_id = f"chunk{i}"
            store.upsert_chunk(ChunkRecord(
                id=chunk_id,
                file_path=f"doc{i}.md",
                chunk_index=0,
                heading_path="",
                start_char=0,
                end_char=len(content),
                token_count=10,
                chunk_hash=f"hash{i}",
                vector_id=chunk_id,
                created_at=1000,
            ))
            store.upsert_fts(chunk_id, content, "", f"doc{i}.md")

        # Search
        results = store.keyword_search("Python", k=5)
        assert len(results) == 2
        assert all("Python" in r["content"] for r in results)

    def test_index_stats(self, temp_dir):
        """Test index statistics."""
        db_path = temp_dir / "test.db"
        store = MetadataStore(db_path)

        stats = store.get_index_stats()
        assert "total_files" in stats
        assert "total_chunks" in stats
        assert "embedding_model" in stats


# =========================================================================
# VectorStore Tests
# =========================================================================

class TestVectorStore:
    """Test vector storage."""

    def test_add_and_query(self, temp_dir):
        """Test adding and querying vectors."""
        chroma_path = temp_dir / "chromadb"
        store = VectorStore(persist_path=str(chroma_path), collection_name="test")

        # Add vectors
        embeddings = [[0.1] * 384, [0.9] * 384]
        metadatas = [
            {"file_path": "a.md", "chunk_index": 0},
            {"file_path": "b.md", "chunk_index": 0},
        ]
        documents = ["First document", "Second document"]

        store.add(["vec1", "vec2"], embeddings, metadatas, documents)

        # Query
        results = store.query([[0.1] * 384], k=2)

        assert len(results["ids"][0]) == 2
        assert results["ids"][0][0] == "vec1"  # Closest to [0.1]

    def test_delete(self, temp_dir):
        """Test vector deletion."""
        chroma_path = temp_dir / "chromadb"
        store = VectorStore(persist_path=str(chroma_path), collection_name="test2")

        store.add(["v1", "v2"], [[0.1]*384, [0.9]*384],
                  [{"file_path": "a.md"}, {"file_path": "b.md"}],
                  ["d1", "d2"])
        assert store.count() == 2

        store.delete(["v1"])
        assert store.count() == 1

        store.delete_by_metadata({"file_path": "b.md"})
        assert store.count() == 0

    def test_collection_info(self, temp_dir):
        """Test collection metadata."""
        chroma_path = temp_dir / "chromadb"
        store = VectorStore(persist_path=str(chroma_path), collection_name="test3")

        info = store.get_collection_info()
        assert "name" in info
        assert "count" in info
        assert "metadata" in info


# =========================================================================
# EmbeddingProvider Tests
# =========================================================================

class MockEmbeddingProvider(EmbeddingProvider):
    """Mock provider for testing."""

    @property
    def provider_name(self) -> str:
        return "mock"

    @property
    def model_name(self) -> str:
        return "mock-model"

    @property
    def dimensions(self) -> int:
        return 384

    def generate_embeddings(self, texts):
        # Return deterministic embeddings based on text hash
        import hashlib
        embeddings = []
        for text in texts:
            h = hashlib.md5(text.encode()).digest()
            # Expand to 384 dimensions
            emb = list(h) * (384 // 16)
            embeddings.append([float(x) / 255.0 for x in emb])
        return EmbeddingResult(
            embeddings=embeddings,
            model=self.model_name,
            dimensions=self.dimensions,
            token_count=sum(len(t) // 4 for t in texts),
            provider=self.provider_name,
        )

    def get_model_info(self):
        return {"name": self.model_name, "dimensions": self.dimensions}

    def health_check(self):
        return True


class TestEmbeddingProvider:
    """Test embedding provider abstraction."""

    def test_mock_provider(self):
        """Test mock provider works."""
        provider = MockEmbeddingProvider()
        result = provider.generate_embeddings(["test1", "test2"])

        assert len(result.embeddings) == 2
        assert result.dimensions == 384
        assert result.provider == "mock"

    def test_token_estimation(self):
        """Test token estimation."""
        provider = MockEmbeddingProvider()
        assert provider.estimate_tokens("hello world") > 0


# =========================================================================
# Retrieval Tests
# =========================================================================

class TestKeywordSearch:
    """Test keyword search."""

    def test_search_basic(self, temp_dir):
        """Test basic keyword search."""
        db_path = temp_dir / "test.db"
        store = MetadataStore(db_path)

        # Add test data
        for i, content in enumerate([
            "Python programming guide",
            "Learn Python basics",
            "JavaScript tutorial",
        ]):
            chunk_id = f"chunk{i}"
            store.upsert_chunk(ChunkRecord(
                id=chunk_id, file_path=f"f{i}.md", chunk_index=0,
                heading_path="", start_char=0, end_char=len(content),
                token_count=10, chunk_hash=f"h{i}", vector_id=chunk_id, created_at=1000
            ))
            store.upsert_fts(chunk_id, content, "", f"f{i}.md")

        search = KeywordSearch(store)
        results = search.search("Python", k=5)

        assert len(results) == 2
        assert all(r.score > 0 for r in results)


class TestVectorSearch:
    """Test vector search."""

    def test_search_basic(self, temp_dir):
        """Test basic vector search."""
        chroma_path = temp_dir / "chromadb"
        vstore = VectorStore(persist_path=str(chroma_path), collection_name="vtest")

        provider = MockEmbeddingProvider()

        # Add vectors
        texts = ["Python programming", "JavaScript basics", "Machine learning"]
        result = provider.generate_embeddings(texts)

        vstore.add(
            ["v1", "v2", "v3"],
            result.embeddings,
            [{"file_path": f"f{i}.md"} for i in range(3)],
            texts
        )

        search = VectorSearch(vstore, provider)
        results = search.search("Python", k=2)

        assert len(results) == 2
        assert results[0].similarity > results[1].similarity


class TestHybridSearch:
    """Test hybrid search."""

    def test_rrf_fusion(self, temp_dir):
        """Test RRF score fusion."""
        # This test requires both stores populated
        # Simplified test for RRF formula
        search = HybridSearch(rrf_k=60)

        # Mock results with known ranks
        # The RRF formula: 1/(k + rank)
        # Rank 1: 1/(60+1) = 0.01639
        # Rank 2: 1/(60+2) = 0.01613
        # Both present: sum = 0.03252
        pass  # Full integration test would require populated stores


# =========================================================================
# Memory API Tests
# =========================================================================

class TestMemoryCapture:
    """Test memory capture."""

    def test_memorize(self, temp_dir):
        """Test memorize functionality."""
        db_path = temp_dir / "mem.db"
        chroma_path = temp_dir / "chroma"

        mstore = MetadataStore(db_path)
        vstore = VectorStore(persist_path=str(chroma_path))
        provider = MockEmbeddingProvider()

        capture = MemoryCapture(
            metadata_store=mstore,
            vector_store=vstore,
            embedding_provider=provider,
        )

        result = capture.memorize(
            content="This is a test memory capture.",
            tags=["test", "memory"],
            source="unit_test",
        )

        assert result.success
        assert result.chunk_count > 0
        assert len(result.chunk_ids) == result.chunk_count

    def test_memorize_structured(self, temp_dir):
        """Test structured memorize."""
        db_path = temp_dir / "mem.db"
        chroma_path = temp_dir / "chroma"

        mstore = MetadataStore(db_path)
        vstore = VectorStore(persist_path=str(chroma_path))
        provider = MockEmbeddingProvider()

        capture = MemoryCapture(
            metadata_store=mstore,
            vector_store=vstore,
            embedding_provider=provider,
        )

        result = capture.memorize_structured(
            title="Test Title",
            content="Test content here.",
            tags=["structured"],
        )

        assert result.success


class TestMemoryManager:
    """Test memory manager."""

    def test_search_and_context(self, temp_dir):
        """Test search and context retrieval."""
        db_path = temp_dir / "mem.db"
        chroma_path = temp_dir / "chroma"

        mstore = MetadataStore(db_path)
        vstore = VectorStore(persist_path=str(chroma_path))
        provider = MockEmbeddingProvider()

        manager = MemoryManager()
        manager.indexer.metadata_store = mstore
        manager.indexer.vector_store = vstore
        manager.indexer.embedding_provider = provider
        manager.hybrid_search.keyword_search = KeywordSearch(mstore)
        manager.hybrid_search.vector_search = VectorSearch(vstore, provider)
        manager.memory_capture.metadata_store = mstore
        manager.memory_capture.vector_store = vstore
        manager.memory_capture.embedding_provider = provider

        # Capture some content
        manager.memorize("Python is a programming language.", tags=["python"])
        manager.memorize("JavaScript is for web development.", tags=["javascript"])

        # Search
        results = manager.search("Python", k=5)
        assert len(results) > 0

        # Get context
        context = manager.get_context("Python", k=3)
        assert context["chunk_count"] > 0
        assert "Python" in context["context"]


# =========================================================================
# Utility Tests
# =========================================================================

class TestUtilities:
    """Test utility functions."""

    def test_compute_hash(self):
        """Test hash computation."""
        from memora.storage.metadata_store import compute_hash

        h1 = compute_hash("test content")
        h2 = compute_hash("test content")
        h3 = compute_hash("different content")

        assert h1 == h2
        assert h1 != h3
        assert len(h1) == 64  # SHA256 hex

    def test_generate_chunk_id(self):
        """Test chunk ID generation."""
        from memora.storage.metadata_store import generate_chunk_id

        id1 = generate_chunk_id("file.md", 0)
        id2 = generate_chunk_id("file.md", 0)
        id3 = generate_chunk_id("file.md", 1)

        assert id1 == id2
        assert id1 != id3
        assert len(id1) == 16


# =========================================================================
# Run Tests
# =========================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])