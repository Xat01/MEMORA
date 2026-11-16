"""
Tests for Indexer.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock

from memora.ingestion.indexer import Indexer, create_indexer
from memora.ingestion.vault_reader import VaultReader, VaultFile
from memora.ingestion.chunker import TextChunk
from memora.embeddings.base import EmbeddingProvider, EmbeddingResult
from memora.storage.metadata_store import MetadataStore
from memora.storage.vector_store import VectorStore


class MockEmbeddingProvider(EmbeddingProvider):
    """Mock embedding provider for testing."""

    @property
    def provider_name(self) -> str:
        return "mock"

    @property
    def model_name(self) -> str:
        return "mock-model"

    @property
    def dimensions(self) -> int:
        return 384

    def generate_embeddings(self, texts: list[str]) -> EmbeddingResult:
        embeddings = [[0.1] * 384 for _ in texts]
        return EmbeddingResult(
            embeddings=embeddings,
            model=self.model_name,
            dimensions=self.dimensions,
            token_count=sum(len(t) // 4 for t in texts),
            provider=self.provider_name,
        )

    def get_model_info(self) -> dict:
        return {"name": self.model_name, "dimensions": self.dimensions}

    def health_check(self) -> bool:
        return True


class TestIndexer:
    """Test Indexer functionality."""

    @pytest.fixture
    def mock_vault_reader(self):
        """Create a mock vault reader."""
        reader = Mock(spec=VaultReader)
        reader.list_files.return_value = ["test.md", "test2.md"]
        return reader

    @pytest.fixture
    def sample_vault_files(self):
        """Create sample vault files."""
        file1 = VaultFile(
            path="test.md",
            name="test.md",
            stem="test",
            content="# Test\n\nContent here.",
            frontmatter={"title": "Test", "tags": ["test"]},
            tags=["test"],
            headings=["Test"],
            size=100,
            mtime=1700000000000,
        )
        file2 = VaultFile(
            path="test2.md",
            name="test2.md",
            stem="test2",
            content="# Test 2\n\nMore content.",
            frontmatter={"title": "Test 2", "tags": ["test2"]},
            tags=["test2"],
            headings=["Test 2"],
            size=200,
            mtime=1700000001000,
        )
        return [file1, file2]

    def test_index_new_files(self, test_config, temp_dir, sample_vault_files):
        """Test indexing new files."""
        # Create mock components
        metadata_store = MetadataStore(db_path=temp_dir / "meta.db")
        vector_store = VectorStore(
            persist_path=str(temp_dir / "chromadb"),
            collection_name="test_indexer"
        )
        embedding_provider = MockEmbeddingProvider()
        vault_reader = Mock(spec=VaultReader)
        vault_reader.list_files.return_value = ["test.md"]
        vault_reader.read_file.return_value = sample_vault_files[0]

        indexer = Indexer(
            metadata_store=metadata_store,
            vector_store=vector_store,
            embedding_provider=embedding_provider,
            vault_reader=vault_reader,
        )

        stats = indexer.index(full_reindex=True)

        assert stats.files_processed == 1
        assert stats.files_indexed == 1
        assert stats.chunks_created >= 1
        assert stats.embeddings_generated >= 1

        # Verify file tracked
        file_record = metadata_store.get_file("test.md")
        assert file_record is not None
        assert file_record.status == "indexed"

        # Verify chunks stored
        chunks = metadata_store.get_chunks_by_file("test.md")
        assert len(chunks) >= 1

        # Verify vectors stored
        assert vector_store.count() >= 1

    def test_index_incremental_no_changes(self, test_config, temp_dir, sample_vault_files):
        """Test incremental indexing skips unchanged files."""
        metadata_store = MetadataStore(db_path=temp_dir / "meta.db")
        vector_store = VectorStore(
            persist_path=str(temp_dir / "chromadb"),
            collection_name="test_indexer2"
        )
        embedding_provider = MockEmbeddingProvider()
        vault_reader = Mock(spec=VaultReader)
        vault_reader.list_files.return_value = ["test.md"]
        vault_reader.read_file.return_value = sample_vault_files[0]

        indexer = Indexer(
            metadata_store=metadata_store,
            vector_store=vector_store,
            embedding_provider=embedding_provider,
            vault_reader=vault_reader,
        )

        # First index
        stats1 = indexer.index(full_reindex=True)
        assert stats1.files_indexed == 1

        # Second index (should skip unchanged)
        stats2 = indexer.index(full_reindex=False)
        assert stats2.files_indexed == 0
        assert stats2.files_skipped == 1

    def test_index_detects_modified_files(self, test_config, temp_dir, sample_vault_files):
        """Test modified files are re-indexed."""
        metadata_store = MetadataStore(db_path=temp_dir / "meta.db")
        vector_store = VectorStore(
            persist_path=str(temp_dir / "chromadb"),
            collection_name="test_indexer3"
        )
        embedding_provider = MockEmbeddingProvider()
        vault_reader = Mock(spec=VaultReader)

        # First version
        file_v1 = VaultFile(
            path="test.md",
            name="test.md",
            stem="test",
            content="# Test\n\nOriginal content.",
            frontmatter={"title": "Test"},
            tags=[],
            headings=["Test"],
            size=100,
            mtime=1700000000000,
        )

        # Modified version
        file_v2 = VaultFile(
            path="test.md",
            name="test.md",
            stem="test",
            content="# Test\n\nModified content.",
            frontmatter={"title": "Test"},
            tags=[],
            headings=["Test"],
            size=120,
            mtime=1700000001000,
        )

        vault_reader.list_files.return_value = ["test.md"]
        vault_reader.read_file.return_value = file_v1

        indexer = Indexer(
            metadata_store=metadata_store,
            vector_store=vector_store,
            embedding_provider=embedding_provider,
            vault_reader=vault_reader,
        )

        # Index v1
        indexer.index(full_reindex=True)

        # Update mock to return v2
        vault_reader.read_file.return_value = file_v2

        # Index again - should detect modification
        stats = indexer.index(full_reindex=False)

        assert stats.files_indexed == 1
        assert stats.files_skipped == 0

    def test_index_deletes_removed_files(self, test_config, temp_dir, sample_vault_files):
        """Test deleted files are removed from index."""
        metadata_store = MetadataStore(db_path=temp_dir / "meta.db")
        vector_store = VectorStore(
            persist_path=str(temp_dir / "chromadb"),
            collection_name="test_indexer4"
        )
        embedding_provider = MockEmbeddingProvider()
        vault_reader = Mock(spec=VaultReader)

        # Initially two files
        vault_reader.list_files.return_value = ["test.md", "test2.md"]
        vault_reader.read_file.side_effect = lambda p: sample_vault_files[0] if p == "test.md" else sample_vault_files[1]

        indexer = Indexer(
            metadata_store=metadata_store,
            vector_store=vector_store,
            embedding_provider=embedding_provider,
            vault_reader=vault_reader,
        )

        # Index both
        indexer.index(full_reindex=True)
        assert metadata_store.get_file("test.md") is not None
        assert metadata_store.get_file("test2.md") is not None

        # Now only one file exists
        vault_reader.list_files.return_value = ["test.md"]
        vault_reader.read_file.return_value = sample_vault_files[0]

        # Re-index
        stats = indexer.index(full_reindex=False)

        assert stats.files_deleted == 1
        assert metadata_store.get_file("test2.md") is None
        assert metadata_store.get_file("test.md") is not None

    def test_reindex_file(self, test_config, temp_dir, sample_vault_files):
        """Test force re-indexing a specific file."""
        metadata_store = MetadataStore(db_path=temp_dir / "meta.db")
        vector_store = VectorStore(
            persist_path=str(temp_dir / "chromadb"),
            collection_name="test_indexer5"
        )
        embedding_provider = MockEmbeddingProvider()
        vault_reader = Mock(spec=VaultReader)
        vault_reader.read_file.return_value = sample_vault_files[0]

        indexer = Indexer(
            metadata_store=metadata_store,
            vector_store=vector_store,
            embedding_provider=embedding_provider,
            vault_reader=vault_reader,
        )

        # Force re-index
        result = indexer.reindex_file("test.md")
        assert result is True

        # Verify indexed
        assert metadata_store.get_file("test.md") is not None

    def test_reindex_nonexistent_file(self, test_config, temp_dir):
        """Test re-indexing non-existent file returns False."""
        metadata_store = MetadataStore(db_path=temp_dir / "meta.db")
        vector_store = VectorStore(
            persist_path=str(temp_dir / "chromadb"),
            collection_name="test_indexer6"
        )
        embedding_provider = MockEmbeddingProvider()
        vault_reader = Mock(spec=VaultReader)
        vault_reader.read_file.return_value = None

        indexer = Indexer(
            metadata_store=metadata_store,
            vector_store=vector_store,
            embedding_provider=embedding_provider,
            vault_reader=vault_reader,
        )

        result = indexer.reindex_file("nonexistent.md")
        assert result is False

    def test_get_status(self, test_config, temp_dir, sample_vault_files):
        """Test getting index status."""
        metadata_store = MetadataStore(db_path=temp_dir / "meta.db")
        vector_store = VectorStore(
            persist_path=str(temp_dir / "chromadb"),
            collection_name="test_indexer7"
        )
        embedding_provider = MockEmbeddingProvider()
        vault_reader = Mock(spec=VaultReader)
        vault_reader.list_files.return_value = ["test.md"]
        vault_reader.read_file.return_value = sample_vault_files[0]

        indexer = Indexer(
            metadata_store=metadata_store,
            vector_store=vector_store,
            embedding_provider=embedding_provider,
            vault_reader=vault_reader,
        )

        indexer.index(full_reindex=True)
        status = indexer.get_status()

        assert status["total_files"] == 1
        assert status["indexed_files"] == 1
        assert status["total_chunks"] >= 1
        assert status["vector_count"] >= 1

    def test_embedding_config_verification(self, temp_dir):
        """Test embedding model mismatch warning uses embedding provider when no config."""
        metadata_store = MetadataStore(db_path=temp_dir / "meta.db")
        vector_store = VectorStore(
            persist_path=str(temp_dir / "chromadb"),
            collection_name="test_indexer8"
        )
        embedding_provider = MockEmbeddingProvider()
        vault_reader = Mock(spec=VaultReader)
        vault_reader.list_files.return_value = []
        vault_reader.read_file.return_value = None

        # Pre-set different model in metadata
        metadata_store.set_meta("embedding_model", "old-model")
        metadata_store.set_meta("embedding_dimensions", "100")

        # Monkey-patch get_config to raise an exception (simulating no config)
        import memora.ingestion.indexer as indexer_module
        original_get_config = indexer_module.get_config
        indexer_module.get_config = lambda: (_ for _ in ()).throw(Exception("No config"))

        try:
            indexer = Indexer(
                metadata_store=metadata_store,
                vector_store=vector_store,
                embedding_provider=embedding_provider,
                vault_reader=vault_reader,
            )

            # Should update metadata to embedding provider's model (no config)
            assert metadata_store.get_meta("embedding_model") == "mock-model"
            assert metadata_store.get_meta("embedding_dimensions") == "384"
        finally:
            indexer_module.get_config = original_get_config

    def test_index_empty_file(self, test_config, temp_dir):
        """Test indexing empty file."""
        metadata_store = MetadataStore(db_path=temp_dir / "meta.db")
        vector_store = VectorStore(
            persist_path=str(temp_dir / "chromadb"),
            collection_name="test_indexer9"
        )
        embedding_provider = MockEmbeddingProvider()
        vault_reader = Mock(spec=VaultReader)

        empty_file = VaultFile(
            path="empty.md",
            name="empty.md",
            stem="empty",
            content="",
            frontmatter={},
            tags=[],
            headings=[],
            size=0,
            mtime=1700000000000,
        )

        vault_reader.list_files.return_value = ["empty.md"]
        vault_reader.read_file.return_value = empty_file

        indexer = Indexer(
            metadata_store=metadata_store,
            vector_store=vector_store,
            embedding_provider=embedding_provider,
            vault_reader=vault_reader,
        )

        stats = indexer.index(full_reindex=True)

        assert stats.files_indexed == 1
        assert stats.chunks_created == 0
        # File should still be tracked
        assert metadata_store.get_file("empty.md") is not None