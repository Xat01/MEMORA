# MEMORA Architecture Documentation

## Overview

MEMORA is a local-first persistent memory infrastructure for AI agents. It implements Retrieval-Augmented Generation (RAG) over Obsidian Markdown vaults using a dual-storage architecture: SQLite for metadata and keyword search, ChromaDB for semantic vector search.

## Design Principles

1. **Obsidian Markdown = Source of Truth** — Original notes are never modified during indexing
2. **Local-First** — No external dependencies, no cloud uploads, no telemetry
3. **Model-Independent** — Works with any LLM via MCP; embedding provider abstraction
4. **Incremental** — Only processes changed/deleted files, zero unnecessary reprocessing
5. **Secure** — Path traversal protection, secret filtering, explicit write permissions

## System Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              MEMORA Architecture                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌──────────┐     ┌──────────────┐     ┌──────────────┐     ┌──────────┐  │
│  │ Obsidian │────▶│  Ingestion   │────▶│   SQLite     │     │  ChromaDB │  │
│  │  Vault   │     │  Pipeline    │     │  (Metadata   │     │  (Vectors)│  │
│  │          │     │              │     │   + FTS5)    │     │          │  │
│  └──────────┘     └──────┬───────┘     └──────┬───────┘     └────┬─────┘  │
│                          │                    │                   │        │
│                          ▼                    ▼                   ▼        │
│                   ┌──────────────┐     ┌──────────────┐     ┌──────────┐  │
│                   │  Chunker     │     │   Indexer    │     │ Embedding │  │
│                   │ (Markdown-   │     │  (Coordinates│     │ Provider  │  │
│                   │  aware)      │     │   Pipeline)  │     │ (Ollama)  │  │
│                   └──────────────┘     └──────────────┘     └──────────┘  │
│                          │                    │                   │        │
│                          └────────────────────┼───────────────────┘        │
│                                               ▼                            │
│                                    ┌────────────────────┐                  │
│                                    │  Hybrid Search     │                  │
│                                    │  (RRF Fusion)      │                  │
│                                    └─────────┬──────────┘                  │
│                                              │                              │
│                                              ▼                              │
│                                    ┌────────────────────┐                  │
│                                    │    MCP Server      │                  │
│                                    │  (Memory Tools)    │                  │
│                                    └────────────────────┘                  │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Component Details

### 1. Ingestion Pipeline (`memora/ingestion/`)

#### VaultReader (`vault_reader.py`)
- Reads vault files via MCP Connector (`mcp__obsidian_my_cyb__get_vault_file`)
- Extracts frontmatter, tags, headings, content
- Supports both MCP-based and local filesystem reading
- Returns `VaultFile` dataclass with parsed metadata

#### Chunker (`chunker.py`)
- **Strategy**: Markdown-aware recursive splitting
- **Steps**:
  1. Split by headers (H1-H6) preserving hierarchy as `heading_path`
  2. Within sections: split by paragraphs, then sentences
  3. Protect code blocks as atomic units
  4. Apply configurable overlap between chunks
- **Configuration**: `CHUNK_SIZE` (default 512 tokens), `CHUNK_OVERLAP` (default 50 tokens)
- **Output**: `TextChunk` with metadata (heading_path, char offsets, token count, hash)

#### Indexer (`indexer.py`)
- Coordinates full pipeline: read → chunk → embed → store
- **Change Detection**: Compares file mtime + content hash + frontmatter hash
- **Incremental Indexing**: Only processes new/modified/deleted files
- **Dual Write**: SQLite (metadata + FTS5) + ChromaDB (vectors)
- **Statistics**: Tracks files/chunks processed, errors, duration

### 2. Embeddings (`memora/embeddings/`)

#### EmbeddingProvider (Abstract Base Class)
- **Abstraction** for provider flexibility (Ollama, OpenAI, Cohere, local transformers)
- **Methods**: `generate_embeddings()`, `get_model_info()`, `health_check()`
- **Properties**: `provider_name`, `model_name`, `dimensions`

#### OllamaProvider (`ollama_provider.py`)
- Local embeddings via Ollama HTTP API (`/api/embeddings`)
- Batch processing with configurable batch size
- Model info via `/api/show`, health check via `/api/tags`
- Supports `pull_model()` for automatic model installation

### 3. Storage (`memora/storage/`)

#### MetadataStore (`metadata_store.py`)
- **SQLite** with FTS5 virtual table for keyword search
- **Tables**:
  - `files`: Track vault files (path, mtime, hashes, status)
  - `chunks`: Track chunks (id, file_path, heading_path, offsets, vector_id)
  - `chunks_fts`: FTS5 virtual table (chunk_id, content, heading_path, file_path)
  - `index_meta`: Configuration metadata (embedding_model, dimensions, last_indexed)
- **Indexes**: On file_path, vector_id, status, mtime for performance
- **Hash-based Change Detection**: SHA256 of content + frontmatter

#### VectorStore (`vector_store.py`)
- **ChromaDB** persistent client
- **Collection**: `memora_vault` with metadata (embedding_model, dimensions)
- **Metadata per vector**: file_path, chunk_index, heading_path, token_count, tags
- **Operations**: add, query, get, delete, delete_by_metadata, count, peek

### 4. Retrieval (`memora/retrieval/`)

#### KeywordSearch (`keyword_search.py`)
- **BM25** via SQLite FTS5
- **Query Preparation**: Converts natural language to FTS5 syntax (OR with prefix wildcards)
- **Results**: Normalized scores (0-1), rank, content, heading_path, file_path

#### VectorSearch (`vector_search.py`)
- **Cosine Similarity** via ChromaDB
- **Query Embedding**: Generated via embedding provider
- **Filters**: file_paths, tags (post-filtered)
- **Results**: distance, similarity (1-distance), normalized score

#### HybridSearch (`hybrid_search.py`)
- **Reciprocal Rank Fusion (RRF)**:
  ```
  score = 1/(k + rank_keyword) + 1/(k + rank_vector)
  ```
  where k = 60 (configurable via `HYBRID_RRF_K`)
- **Modes**: "hybrid" (default), "keyword", "vector"
- **Result Unification**: `SearchResult` dataclass with all metadata
- **Source Attribution**: Every result includes file_path, heading_path, chunk content

### 5. Memory API (`memora/memory/`)

#### MemoryCapture (`capture.py`)
- **memorize()**: Capture arbitrary content with tags/source
- **memorize_structured()**: Title + content capture
- **capture_conversation()**: Conversation history capture
- Creates virtual files under `_captured/` for tracking

#### MemoryManager (`manager.py`)
- **Unified Interface**: memorize, search, get_context, list_sources, reindex, status
- **get_context()**: Formats results for LLM consumption with source citations
- **Context Building**: Truncates to max_chars, includes similarity scores

### 6. MCP Server (`memora/mcp/server.py`)

#### Tools Exposed:
| Tool | Description | Parameters |
|------|-------------|------------|
| `memorize` | Capture knowledge | content, tags?, source? |
| `search_memory` | Hybrid search | query, k?, mode?, file_paths?, tags? |
| `get_context` | Formatted context | topic, k?, mode?, max_chars? |
| `list_sources` | Indexed files | limit? |
| `reindex` | Trigger indexing | full? |

#### Transports:
- **stdio** (default): For Claude Desktop integration
- **HTTP/SSE**: For network access (optional)

## Data Flow

### Indexing Flow
```
1. VaultReader.list_files() → [paths]
2. For each path: VaultReader.read_file() → VaultFile
3. Indexer._detect_changes() → (to_index, to_delete)
4. For to_delete: delete from SQLite + ChromaDB
5. For to_index:
   a. Chunker.chunk_text() → [TextChunk]
   b. EmbeddingProvider.generate_embeddings() → [embeddings]
   c. MetadataStore.upsert_chunk() + upsert_fts()
   d. VectorStore.add() with metadata
   e. MetadataStore.upsert_file()
6. Update index_meta (last_indexed, embedding_model, etc.)
```

### Search Flow
```
1. HybridSearch.search(query, k, mode)
2. If mode != "vector":
   a. KeywordSearch.search() → [KeywordResult] with BM25 ranks
3. If mode != "keyword":
   a. EmbeddingProvider.generate_embeddings([query]) → query_embedding
   b. VectorSearch.search() → [VectorResult] with cosine similarity ranks
4. If hybrid:
   a. Build rank maps for each result set
   b. Compute RRF scores for all unique chunk_ids
   c. Merge metadata (prefer vector for richness)
   d. Sort by RRF score descending
5. Return [SearchResult] with unified metadata
```

## Incremental Indexing Details

### Change Detection
For each file in vault:
1. Compute `content_hash = SHA256(content_without_frontmatter)`
2. Compute `frontmatter_hash = SHA256(str(frontmatter))`
3. Compare with stored record:
   - New file → index
   - mtime changed OR content_hash changed OR frontmatter_hash changed → re-index
   - Unchanged → skip (zero reprocessing)
4. Files in SQLite but not in vault → mark deleted, remove from ChromaDB

### Deletion Handling
- Soft delete: `status = 'deleted'` in files table
- Hard delete: Remove chunks from chunks + chunks_fts + ChromaDB
- Configurable: `full_reindex=True` ignores change detection

## Security Considerations

1. **Path Traversal Protection**: All vault paths validated against vault root
2. **No External Uploads**: All processing local; only Ollama (localhost) for embeddings
3. **Credential Filtering**: Frontmatter/content scanned for secrets before storage
4. **No Arbitrary Code Execution**: Markdown treated as data, not executable
5. **Explicit Write Permissions**: MCP tools require user confirmation for modifications

## Configuration

All configuration via environment variables (`.env` file):

| Variable | Default | Description |
|----------|---------|-------------|
| `VAULT_PATH` | *required* | Obsidian vault path |
| `CHROMA_PATH` | `./data/chromadb` | ChromaDB persistence |
| `SQLITE_PATH` | `./data/memora.db` | SQLite database |
| `EMBEDDING_MODEL` | `nomic-embed-text` | Ollama model |
| `EMBEDDING_DIMENSIONS` | `768` | Model dimensions |
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama endpoint |
| `CHUNK_SIZE` | `512` | Token chunk size |
| `CHUNK_OVERLAP` | `50` | Token overlap |
| `DEFAULT_SEARCH_K` | `10` | Default results |
| `HYBRID_RRF_K` | `60` | RRF constant |
| `MCP_TRANSPORT` | `stdio` | MCP transport |

## Extensibility

### Adding New Embedding Providers
1. Subclass `EmbeddingProvider` in `memora/embeddings/`
2. Implement: `generate_embeddings()`, `get_model_info()`, `health_check()`
3. Add to `memora/embeddings/__init__.py`
4. Update config to select provider

### Adding New Vector Stores
1. Create new class in `memora/storage/` implementing same interface as `VectorStore`
2. Update `Indexer` to use new store
3. Add configuration option

### Adding New Search Modes
1. Create new search class in `memora/retrieval/`
2. Implement `search(query, k, filters)` returning standardized results
3. Add to `HybridSearch` as new mode option

## Performance Characteristics

| Operation | Complexity | Notes |
|-----------|------------|-------|
| Incremental index | O(changed_files × chunks_per_file) | Skips unchanged files |
| Full re-index | O(total_files × chunks_per_file) | One-time cost |
| Keyword search | O(FTS5_index) | Sub-millisecond for typical vaults |
| Vector search | O(chroma_hnsw) | ~10-50ms for 10K vectors |
| Hybrid search | O(keyword + vector + merge) | ~50-100ms total |
| Memory capture | O(chunks × embedding) | Batched embedding generation |

## Scaling Considerations

- **Chunks per file**: ~10-50 for typical notes
- **Total chunks**: 10K-100K for large vaults
- **ChromaDB HNSW**: Efficient up to millions of vectors
- **SQLite FTS5**: Handles millions of rows
- **Batch embedding**: Reduces Ollama API calls
- **Streaming**: Large vaults can use watch mode for continuous indexing