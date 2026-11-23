"""
Tests for MetadataStore.
"""

import pytest
from memora.storage.metadata_store import (
    MetadataStore, FileRecord, ChunkRecord,
    compute_hash, generate_chunk_id
)


class TestMetadataStore:
    """Test MetadataStore functionality."""

    def test_init_creates_tables(self, test_config, temp_dir):
        """Test database initialization creates all tables."""
        db_path = temp_dir / "test.db"
        store = MetadataStore(db_path=db_path)

        # Check tables exist
        with store._conn() as conn:
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            table_names = {row[0] for row in tables}

            assert "files" in table_names
            assert "chunks" in table_names
            assert "chunks_fts" in table_names
            assert "index_meta" in table_names

    def test_upsert_and_get_file(self, test_config, temp_dir):
        """Test inserting and retrieving file records."""
        db_path = temp_dir / "test.db"
        store = MetadataStore(db_path=db_path)

        record = FileRecord(
            path="test.md",
            mtime=1700000000000,
            size=1024,
            frontmatter_hash="abc123",
            content_hash="def456",
            indexed_at=1700000000000,
            status="indexed",
        )

        store.upsert_file(record)
        retrieved = store.get_file("test.md")

        assert retrieved is not None
        assert retrieved.path == "test.md"
        assert retrieved.mtime == 1700000000000
        assert retrieved.size == 1024
        assert retrieved.frontmatter_hash == "abc123"
        assert retrieved.content_hash == "def456"
        assert retrieved.status == "indexed"

    def test_upsert_file_updates_existing(self, test_config, temp_dir):
        """Test upsert updates existing record."""
        db_path = temp_dir / "test.db"
        store = MetadataStore(db_path=db_path)

        record1 = FileRecord(
            path="test.md",
            mtime=1700000000000,
            size=1024,
            frontmatter_hash="abc123",
            content_hash="def456",
            indexed_at=1700000000000,
            status="indexed",
        )
        store.upsert_file(record1)

        record2 = FileRecord(
            path="test.md",
            mtime=1700000001000,
            size=2048,
            frontmatter_hash="abc123",
            content_hash="new_hash",
            indexed_at=1700000001000,
            status="modified",
        )
        store.upsert_file(record2)

        retrieved = store.get_file("test.md")
        assert retrieved.mtime == 1700000001000
        assert retrieved.size == 2048
        assert retrieved.content_hash == "new_hash"
        assert retrieved.status == "modified"

    def test_get_all_files(self, test_config, temp_dir):
        """Test retrieving all file records."""
        db_path = temp_dir / "test.db"
        store = MetadataStore(db_path=db_path)

        for i in range(3):
            store.upsert_file(FileRecord(
                path=f"file{i}.md",
                mtime=1700000000000 + i,
                size=1000 + i,
                frontmatter_hash=f"fm{i}",
                content_hash=f"ch{i}",
                indexed_at=1700000000000 + i,
                status="indexed",
            ))

        files = store.get_all_files()
        assert len(files) == 3

    def test_get_files_by_status(self, test_config, temp_dir):
        """Test filtering files by status."""
        db_path = temp_dir / "test.db"
        store = MetadataStore(db_path=db_path)

        store.upsert_file(FileRecord(
            path="indexed.md", mtime=1, size=1,
            frontmatter_hash="a", content_hash="b",
            indexed_at=1, status="indexed"
        ))
        store.upsert_file(FileRecord(
            path="modified.md", mtime=2, size=2,
            frontmatter_hash="c", content_hash="d",
            indexed_at=2, status="modified"
        ))
        store.upsert_file(FileRecord(
            path="deleted.md", mtime=3, size=3,
            frontmatter_hash="e", content_hash="f",
            indexed_at=3, status="deleted"
        ))

        indexed = store.get_files_by_status("indexed")
        modified = store.get_files_by_status("modified")
        deleted = store.get_files_by_status("deleted")

        assert len(indexed) == 1
        assert indexed[0].path == "indexed.md"
        assert len(modified) == 1
        assert modified[0].path == "modified.md"
        assert len(deleted) == 1
        assert deleted[0].path == "deleted.md"

    def test_mark_deleted(self, test_config, temp_dir):
        """Test marking file as deleted."""
        db_path = temp_dir / "test.db"
        store = MetadataStore(db_path=db_path)

        store.upsert_file(FileRecord(
            path="test.md", mtime=1, size=1,
            frontmatter_hash="a", content_hash="b",
            indexed_at=1, status="indexed"
        ))

        store.mark_deleted("test.md")
        retrieved = store.get_file("test.md")

        assert retrieved.status == "deleted"

    def test_delete_file_record(self, test_config, temp_dir):
        """Test permanently deleting file record."""
        db_path = temp_dir / "test.db"
        store = MetadataStore(db_path=db_path)

        store.upsert_file(FileRecord(
            path="test.md", mtime=1, size=1,
            frontmatter_hash="a", content_hash="b",
            indexed_at=1, status="indexed"
        ))

        # Add a chunk
        store.upsert_chunk(ChunkRecord(
            id="chunk1", file_path="test.md", chunk_index=0,
            heading_path="", start_char=0, end_char=100,
            token_count=25, chunk_hash="hash1", vector_id="vec1",
            created_at=1
        ))

        store.delete_file_record("test.md")

        assert store.get_file("test.md") is None
        assert store.get_chunks_by_file("test.md") == []

    def test_upsert_and_get_chunk(self, test_config, temp_dir):
        """Test inserting and retrieving chunk records."""
        db_path = temp_dir / "test.db"
        store = MetadataStore(db_path=db_path)

        chunk = ChunkRecord(
            id="chunk1",
            file_path="test.md",
            chunk_index=0,
            heading_path="Header::Subheader",
            start_char=0,
            end_char=100,
            token_count=25,
            chunk_hash="abc123",
            vector_id="vec1",
            created_at=1700000000000,
        )

        store.upsert_chunk(chunk)
        retrieved = store.get_chunk("chunk1")

        assert retrieved is not None
        assert retrieved.id == "chunk1"
        assert retrieved.file_path == "test.md"
        assert retrieved.chunk_index == 0
        assert retrieved.heading_path == "Header::Subheader"
        assert retrieved.token_count == 25

    def test_get_chunks_by_file(self, test_config, temp_dir):
        """Test retrieving all chunks for a file."""
        db_path = temp_dir / "test.db"
        store = MetadataStore(db_path=db_path)

        for i in range(3):
            store.upsert_chunk(ChunkRecord(
                id=f"chunk{i}",
                file_path="test.md",
                chunk_index=i,
                heading_path=f"Section {i}",
                start_char=i * 100,
                end_char=(i + 1) * 100,
                token_count=25,
                chunk_hash=f"hash{i}",
                vector_id=f"vec{i}",
                created_at=1700000000000 + i,
            ))

        chunks = store.get_chunks_by_file("test.md")
        assert len(chunks) == 3
        assert chunks[0].chunk_index == 0
        assert chunks[1].chunk_index == 1
        assert chunks[2].chunk_index == 2

    def test_batch_upsert_chunks(self, test_config, temp_dir):
        """Test batch upserting chunk records in a single transaction."""
        db_path = temp_dir / "test.db"
        store = MetadataStore(db_path=db_path)

        records = [
            ChunkRecord(
                id=f"batch_chunk_{i}",
                file_path="batch.md",
                chunk_index=i,
                heading_path=f"Batch {i}",
                start_char=i * 50,
                end_char=(i + 1) * 50,
                token_count=12,
                chunk_hash=f"bhash_{i}",
                vector_id=f"bvec_{i}",
                created_at=1000 + i,
            )
            for i in range(10)
        ]

        store.batch_upsert_chunks(records)
        chunks = store.get_chunks_by_file("batch.md")
        assert len(chunks) == 10
        assert chunks[5].id == "batch_chunk_5"

    def test_batch_upsert_fts(self, test_config, temp_dir):
        """Test batch upserting FTS5 entries in a single transaction."""
        db_path = temp_dir / "test.db"
        store = MetadataStore(db_path=db_path)

        fts_entries = [
            (f"chunk_{i}", f"This is sample text number {i} talking about security", f"Heading {i}", f"file_{i}.md")
            for i in range(5)
        ]

        store.batch_upsert_fts(fts_entries)
        results = store.keyword_search("security", k=10)
        assert len(results) == 5

    def test_delete_chunks_by_file(self, test_config, temp_dir):
        """Test deleting all chunks for a file."""
        db_path = temp_dir / "test.db"
        store = MetadataStore(db_path=db_path)

        for i in range(3):
            store.upsert_chunk(ChunkRecord(
                id=f"chunk{i}", file_path="test.md", chunk_index=i,
                heading_path="", start_char=0, end_char=100,
                token_count=25, chunk_hash=f"hash{i}", vector_id=f"vec{i}",
                created_at=1
            ))

        store.delete_chunks_by_file("test.md")
        chunks = store.get_chunks_by_file("test.md")
        assert chunks == []

    def test_fts_upsert_and_search(self, test_config, temp_dir):
        """Test FTS5 upsert and keyword search."""
        db_path = temp_dir / "test.db"
        store = MetadataStore(db_path=db_path)

        store.upsert_fts("chunk1", "machine learning fundamentals", "ML", "test.md")
        store.upsert_fts("chunk2", "deep learning neural networks", "DL", "test.md")
        store.upsert_fts("chunk3", "supervised learning classification", "ML", "test.md")

        results = store.keyword_search("learning", k=10)
        assert len(results) == 3
        # All should contain "learning"
        for r in results:
            assert "learning" in r["content"].lower()

    def test_fts_search_ranking(self, test_config, temp_dir):
        """Test BM25 ranking in FTS5 search."""
        db_path = temp_dir / "test.db"
        store = MetadataStore(db_path=db_path)

        # Document with more occurrences should rank higher
        store.upsert_fts("chunk1", "learning learning learning learning", "", "test.md")
        store.upsert_fts("chunk2", "learning once", "", "test.md")
        store.upsert_fts("chunk3", "no match here", "", "test.md")

        results = store.keyword_search("learning", k=10)
        assert len(results) >= 2
        # First result should have more occurrences (lower BM25 rank = better)
        assert results[0]["chunk_id"] == "chunk1"

    def test_fts_delete(self, test_config, temp_dir):
        """Test FTS5 delete."""
        db_path = temp_dir / "test.db"
        store = MetadataStore(db_path=db_path)

        store.upsert_fts("chunk1", "test content", "", "test.md")
        store.delete_fts("chunk1")

        results = store.keyword_search("test", k=10)
        assert len(results) == 0

    def test_index_meta(self, test_config, temp_dir):
        """Test index metadata storage."""
        db_path = temp_dir / "test.db"
        store = MetadataStore(db_path=db_path)

        store.set_meta("key1", "value1")
        store.set_meta("key2", "value2")

        assert store.get_meta("key1") == "value1"
        assert store.get_meta("key2") == "value2"
        assert store.get_meta("nonexistent") is None
        assert store.get_meta("nonexistent", "default") == "default"

        # Update existing
        store.set_meta("key1", "updated")
        assert store.get_meta("key1") == "updated"

    def test_get_index_stats(self, test_config, temp_dir):
        """Test index statistics."""
        db_path = temp_dir / "test.db"
        store = MetadataStore(db_path=db_path)

        store.upsert_file(FileRecord(
            path="indexed.md", mtime=1, size=1,
            frontmatter_hash="a", content_hash="b",
            indexed_at=1, status="indexed"
        ))
        store.upsert_file(FileRecord(
            path="modified.md", mtime=2, size=2,
            frontmatter_hash="c", content_hash="d",
            indexed_at=2, status="modified"
        ))
        store.upsert_file(FileRecord(
            path="deleted.md", mtime=3, size=3,
            frontmatter_hash="e", content_hash="f",
            indexed_at=3, status="deleted"
        ))

        stats = store.get_index_stats()
        assert stats["total_files"] == 2  # Not counting deleted
        assert stats["indexed_files"] == 1
        assert stats["modified_files"] == 1
        assert stats["deleted_files"] == 1

    def test_compute_hash(self):
        """Test hash computation."""
        hash1 = compute_hash("test content")
        hash2 = compute_hash("test content")
        hash3 = compute_hash("different content")

        assert hash1 == hash2  # Deterministic
        assert hash1 != hash3  # Different content = different hash
        assert len(hash1) == 64  # SHA256 hex

    def test_generate_chunk_id(self):
        """Test deterministic chunk ID generation."""
        id1 = generate_chunk_id("test.md", 0)
        id2 = generate_chunk_id("test.md", 0)
        id3 = generate_chunk_id("test.md", 1)

        assert id1 == id2  # Deterministic
        assert id1 != id3  # Different index = different ID
        assert len(id1) == 16  # Truncated hash