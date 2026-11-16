---
name: memora
description: "MEMORA — Local-first persistent memory infrastructure for AI agents. Provides RAG capabilities over Obsidian vault with MCP server."
version: 1
---

# MEMORA Skill

> **MEMORA** — Local-First Persistent Memory Infrastructure for AI Agents

---

## Purpose

This skill provides commands to interact with the MEMORA memory infrastructure:
- Index and search your Obsidian vault
- Capture knowledge with automatic embedding generation
- Retrieve context via hybrid search (keyword + semantic)
- Manage the MEMORA MCP server

---

## Commands

### `memora:index`
**Full or incremental vault indexing**
```
memora:index [--full] [--watch]
```
- `--full` — Full re-index (ignore change detection)
- `--watch` — Watch mode for continuous indexing

### `memora:search`
**Hybrid search across indexed vault**
```
memora:search <query> [--k=10] [--mode=hybrid|keyword|vector] [--tags=tag1,tag2]
```
- `--k` — Number of results (default: 10)
- `--mode` — Search mode: hybrid (default), keyword, or vector
- `--tags` — Filter by tags (comma-separated)

### `memora:capture`
**Capture knowledge into memory**
```
memora:capture <content> [--tags=tag1,tag2] [--source=description]
```
- `--tags` — Tags for the captured knowledge
- `--source` — Source description (e.g., "session:abc123", "manual")

### `memora:context`
**Get relevant context for a topic**
```
memora:context <topic> [--k=5]
```
- Returns formatted context chunks with source references

### `memora:sources`
**List indexed sources**
```
memora:sources [--limit=20]
```

### `memora:server`
**Start MEMORA MCP server**
```
memora:server [--transport=stdio|http] [--port=8080]
```
- `--transport` — Transport protocol (default: stdio)
- `--port` — HTTP port (default: 8080)

### `memora:status`
**Show indexing status and statistics**
```
memora:status
```

---

## Configuration

Environment variables (from `.env`):
- `VAULT_PATH` — **Required** Path to Obsidian vault
- `CHROMA_PATH` — ChromaDB persistence directory (default: `./data/chromadb`)
- `SQLITE_PATH` — SQLite database path (default: `./data/memora.db`)
- `EMBEDDING_MODEL` — Ollama model (default: `nomic-embed-text`)
- `EMBEDDING_DIMENSIONS` — Model dimensions (default: `768`)
- `OLLAMA_HOST` — Ollama API endpoint (default: `http://localhost:11434`)
- `CHUNK_SIZE` — Token chunk size (default: `512`)
- `CHUNK_OVERLAP` — Token overlap (default: `50`)
- `DEFAULT_SEARCH_K` — Default search results (default: `10`)
- `HYBRID_RRF_K` — RRF fusion constant (default: `60`)

---

## MCP Tools (when server running)

| Tool | Description |
|------|-------------|
| `memorize` | Capture knowledge: `memorize(content, tags?, source?)` |
| `search_memory` | Hybrid search: `search_memory(query, k?, mode?)` |
| `get_context` | Get context: `get_context(topic, k?)` |
| `list_sources` | List indexed files |
| `reindex` | Trigger full re-index |

---

## Architecture

```
Obsidian Vault → VaultReader → Chunker → Indexer
                                    ↓
                            SQLite (metadata + FTS5)
                                    ↓
                            Ollama Embeddings
                                    ↓
                            ChromaDB (vectors)
                                    ↓
                            HybridSearch (RRF)
                                    ↓
                            MCP Server → AI Agents
```

---

## Security

- All processing local — no external API calls except Ollama (localhost)
- Path traversal protection on vault operations
- No credential storage in index
- Explicit write permissions required for modifications