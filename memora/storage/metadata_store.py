"""
MEMORA Metadata Store

SQLite-based metadata storage with FTS5 full-text search for keywords.
Tracks files, chunks, and enables incremental indexing.
"""

import hashlib
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from memora.config import get_config


@dataclass
class FileRecord:
    """Represents a tracked vault file."""
    path: str
    mtime: int
    size: int
    frontmatter_hash: str
    content_hash: str
    indexed_at: int
    status: str  # 'indexed', 'modified', 'deleted'


@dataclass
class ChunkRecord:
    """Represents a text chunk with metadata."""
    id: str
    file_path: str
    chunk_index: int
    heading_path: str
    start_char: int
    end_char: int
    token_count: int
    chunk_hash: str
    vector_id: str
    created_at: int


class MetadataStore:
    """
    SQLite metadata store with FTS5 for keyword search.

    Schema:
    - files: Track vault files with hashes for change detection
    - chunks: Track individual chunks with metadata
    - chunks_fts: FTS5 virtual table for full-text search
    """

    def __init__(self, db_path: Optional[Path] = None):
        if db_path is None:
            try:
                self.config = get_config()
                self.db_path = self.config.sqlite_path
            except Exception:
                self.config = None
                self.db_path = Path("./data/memora.db")
        else:
            self.config = None
            self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        """Initialize database schema."""
        with self._conn() as conn:
            conn.executescript("""
                -- Files table: tracks vault files for incremental indexing
                CREATE TABLE IF NOT EXISTS files (
                    path TEXT PRIMARY KEY,
                    mtime INTEGER NOT NULL,
                    size INTEGER NOT NULL,
                    frontmatter_hash TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    indexed_at INTEGER NOT_NULL,
                    status TEXT NOT NULL DEFAULT 'indexed'
                        CHECK (status IN ('indexed', 'modified', 'deleted'))
                );

                -- Chunks table: tracks individual text chunks
                CREATE TABLE IF NOT EXISTS chunks (
                    id TEXT PRIMARY KEY,
                    file_path TEXT NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    heading_path TEXT,
                    start_char INTEGER NOT NULL,
                    end_char INTEGER NOT NULL,
                    token_count INTEGER NOT NULL,
                    chunk_hash TEXT NOT NULL,
                    vector_id TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    FOREIGN KEY (file_path) REFERENCES files(path)
                );

                -- FTS5 virtual table for keyword search
                CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
                    chunk_id UNINDEXED,
                    content,
                    heading_path,
                    file_path,
                    tokenize='porter unicode61'
                );

                -- Indexes for performance
                CREATE INDEX IF NOT EXISTS idx_chunks_file_path ON chunks(file_path);
                CREATE INDEX IF NOT EXISTS idx_chunks_vector_id ON chunks(vector_id);
                CREATE INDEX IF NOT EXISTS idx_files_status ON files(status);
                CREATE INDEX IF NOT EXISTS idx_files_mtime ON files(mtime);

                -- Metadata table for index configuration
                CREATE TABLE IF NOT EXISTS index_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
            """)

    @contextmanager
    def _conn(self):
        """Context manager for database connections."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # =========================================================================
    # File Operations
    # =========================================================================

    def upsert_file(self, record: FileRecord) -> None:
        """Insert or update a file record."""
        with self._conn() as conn:
            conn.execute("""
                INSERT INTO files (path, mtime, size, frontmatter_hash, content_hash, indexed_at, status)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    mtime=excluded.mtime,
                    size=excluded.size,
                    frontmatter_hash=excluded.frontmatter_hash,
                    content_hash=excluded.content_hash,
                    indexed_at=excluded.indexed_at,
                    status=excluded.status
            """, (record.path, record.mtime, record.size, record.frontmatter_hash,
                  record.content_hash, record.indexed_at, record.status))

    def get_file(self, path: str) -> Optional[FileRecord]:
        """Get file record by path."""
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM files WHERE path = ?", (path,)).fetchone()
            if row:
                return FileRecord(**dict(row))
            return None

    def get_all_files(self) -> list[FileRecord]:
        """Get all file records."""
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM files").fetchall()
            return [FileRecord(**dict(row)) for row in rows]

    def get_files_by_status(self, status: str) -> list[FileRecord]:
        """Get files by status."""
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM files WHERE status = ?", (status,)).fetchall()
            return [FileRecord(**dict(row)) for row in rows]

    def mark_deleted(self, path: str) -> None:
        """Mark a file as deleted."""
        with self._conn() as conn:
            conn.execute("UPDATE files SET status = 'deleted' WHERE path = ?", (path,))

    def delete_file_record(self, path: str) -> None:
        """Permanently delete file record and associated chunks."""
        with self._conn() as conn:
            conn.execute("DELETE FROM chunks WHERE file_path = ?", (path,))
            conn.execute("DELETE FROM chunks_fts WHERE file_path = ?", (path,))
            conn.execute("DELETE FROM files WHERE path = ?", (path,))

    # =========================================================================
    # Chunk Operations
    # =========================================================================

    def upsert_chunk(self, record: ChunkRecord) -> None:
        """Insert or update a chunk record."""
        with self._conn() as conn:
            conn.execute("""
                INSERT INTO chunks (id, file_path, chunk_index, heading_path, start_char, end_char,
                                   token_count, chunk_hash, vector_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    file_path=excluded.file_path,
                    chunk_index=excluded.chunk_index,
                    heading_path=excluded.heading_path,
                    start_char=excluded.start_char,
                    end_char=excluded.end_char,
                    token_count=excluded.token_count,
                    chunk_hash=excluded.chunk_hash,
                    vector_id=excluded.vector_id,
                    created_at=excluded.created_at
            """, (record.id, record.file_path, record.chunk_index, record.heading_path,
                  record.start_char, record.end_char, record.token_count,
                  record.chunk_hash, record.vector_id, record.created_at))

    def get_chunk(self, chunk_id: str) -> Optional[ChunkRecord]:
        """Get chunk by ID."""
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM chunks WHERE id = ?", (chunk_id,)).fetchone()
            if row:
                return ChunkRecord(**dict(row))
            return None

    def get_chunks_by_file(self, file_path: str) -> list[ChunkRecord]:
        """Get all chunks for a file."""
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM chunks WHERE file_path = ? ORDER BY chunk_index",
                               (file_path,)).fetchall()
            return [ChunkRecord(**dict(row)) for row in rows]

    def delete_chunks_by_file(self, file_path: str) -> None:
        """Delete all chunks for a file."""
        with self._conn() as conn:
            chunk_ids = [row[0] for row in
                        conn.execute("SELECT id FROM chunks WHERE file_path = ?", (file_path,))]
            if chunk_ids:
                placeholders = ",".join("?" * len(chunk_ids))
                conn.execute(f"DELETE FROM chunks_fts WHERE chunk_id IN ({placeholders})", chunk_ids)
            conn.execute("DELETE FROM chunks WHERE file_path = ?", (file_path,))

    # =========================================================================
    # FTS5 Keyword Search
    # =========================================================================

    def upsert_fts(self, chunk_id: str, content: str, heading_path: str, file_path: str) -> None:
        """Insert or update FTS5 entry for a chunk."""
        with self._conn() as conn:
            # FTS5 doesn't support ON CONFLICT, so delete first then insert
            conn.execute("DELETE FROM chunks_fts WHERE chunk_id = ?", (chunk_id,))
            conn.execute("""
                INSERT INTO chunks_fts (chunk_id, content, heading_path, file_path)
                VALUES (?, ?, ?, ?)
            """, (chunk_id, content, heading_path, file_path))

    def delete_fts(self, chunk_id: str) -> None:
        """Delete FTS5 entry."""
        with self._conn() as conn:
            conn.execute("DELETE FROM chunks_fts WHERE chunk_id = ?", (chunk_id,))

    def keyword_search(self, query: str, k: int = 10) -> list[dict]:
        """
        Full-text search using FTS5 BM25 ranking.

        Returns list of dicts with: chunk_id, content, heading_path, file_path, rank
        """
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT chunk_id, content, heading_path, file_path,
                       bm25(chunks_fts) as rank
                FROM chunks_fts
                WHERE chunks_fts MATCH ?
                ORDER BY rank
                LIMIT ?
            """, (query, k)).fetchall()
            return [dict(row) for row in rows]

    def keyword_search_with_filters(self, query: str, k: int = 10,
                                    file_paths: Optional[list[str]] = None,
                                    tags: Optional[list[str]] = None) -> list[dict]:
        """Keyword search with optional filters (file_paths, tags via join)."""
        # For now, basic implementation - tags would need a tags table
        return self.keyword_search(query, k)

    # =========================================================================
    # Index Metadata
    # =========================================================================

    def set_meta(self, key: str, value: str) -> None:
        """Set index metadata."""
        with self._conn() as conn:
            conn.execute("""
                INSERT INTO index_meta (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """, (key, value))

    def get_meta(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """Get index metadata."""
        with self._conn() as conn:
            row = conn.execute("SELECT value FROM index_meta WHERE key = ?", (key,)).fetchone()
            return row[0] if row else default

    def get_index_stats(self) -> dict:
        """Get index statistics."""
        with self._conn() as conn:
            stats = {}
            stats["total_files"] = conn.execute("SELECT COUNT(*) FROM files WHERE status != 'deleted'").fetchone()[0]
            stats["total_chunks"] = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
            stats["indexed_files"] = conn.execute("SELECT COUNT(*) FROM files WHERE status = 'indexed'").fetchone()[0]
            stats["modified_files"] = conn.execute("SELECT COUNT(*) FROM files WHERE status = 'modified'").fetchone()[0]
            stats["deleted_files"] = conn.execute("SELECT COUNT(*) FROM files WHERE status = 'deleted'").fetchone()[0]
            stats["embedding_model"] = self.get_meta("embedding_model", "unknown")
            stats["embedding_dimensions"] = int(self.get_meta("embedding_dimensions", "0"))
            stats["last_indexed"] = self.get_meta("last_indexed", "never")
            return stats


# =========================================================================
# Utility Functions
# =========================================================================

def compute_hash(content: str) -> str:
    """Compute SHA256 hash of content."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def generate_chunk_id(file_path: str, chunk_index: int) -> str:
    """Generate deterministic chunk ID."""
    return compute_hash(f"{file_path}:{chunk_index}")[:16]