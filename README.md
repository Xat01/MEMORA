# MEMORA

> **Local-First Persistent Memory Infrastructure for AI Agents**

MEMORA is an open-source, model-independent memory infrastructure that enables AI agents to maintain persistent, searchable knowledge across sessions using Retrieval-Augmented Generation (RAG) with Obsidian Markdown as the source of truth.

---

## Features

- **Obsidian Markdown as Source of Truth** — Original notes never modified during indexing
- **Dual Storage** — SQLite for metadata + keyword search (FTS5), ChromaDB for semantic vector search
- **Local Embeddings** — Ollama integration with provider abstraction for flexibility
- **Incremental Indexing** — Only processes changed/deleted files, avoids reprocessing
- **Hybrid Retrieval** — Combines BM25 keyword search with semantic vector search via RRF
- **MCP Server** — Exposes memory capabilities to any MCP-compatible client
- **Security First** — Path traversal protection, no external uploads, secret protection

---

## Architecture

```
┌─────────────┐     ┌─────────────┐     ┌──────────────────┐
│   Obsidian  │────▶│  Ingestion  │────▶│  SQLite (Meta)   │
│   Vault     │     │  Pipeline   │     │  + FTS5 (KW)     │
└─────────────┘     └──────┬──────┘     └──────────────────┘
                           │
                           ▼
                    ┌─────────────┐     ┌──────────────────┐
                    │  Embeddings │────▶│  ChromaDB        │
                    │  (Ollama)   │     │  (Vector Search) │
                    └─────────────┘     └──────────────────┘
                           │
                           ▼
                    ┌──────────────────┐
                    │  Hybrid Search   │
                    │  (RRF Fusion)    │
                    └──────────────────┘
                           │
                           ▼
                    ┌──────────────────┐
                    │   MCP Server     │
                    │  (Memory Tools)  │
                    └──────────────────┘
```

---

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Install and start Ollama
# https://ollama.ai
ollama pull nomic-embed-text

# 3. Configure vault path
cp .env.example .env
# Edit .env with your Obsidian vault path

# 4. Verify installation with diagnostics
memora doctor

# 5. Run initial indexing
memora ingest

# 6. Start MCP server (for Claude Desktop)
memora mcp
```

---

## Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `VAULT_PATH` | Path to Obsidian vault | Required |
| `CHROMA_PATH` | ChromaDB persistence directory | `./data/chromadb` |
| `SQLITE_PATH` | SQLite database path | `./data/memora.db` |
| `EMBEDDING_MODEL` | Ollama embedding model | `nomic-embed-text` |
| `CHUNK_SIZE` | Token chunk size | `512` |
| `CHUNK_OVERLAP` | Token overlap between chunks | `50` |
| `EMBEDDING_DIMENSIONS` | Model output dimensions | `768` (nomic-embed-text) |

See `.env.example` for all options.

---

## CLI Commands

| Command | Description |
|---------|-------------|
| `memora doctor` | Run system diagnostics (health checks) |
| `memora doctor --json` | Output diagnostics as JSON |
| `memora doctor --verbose` | Show detailed output |
| `memora status` | Show index status and configuration |
| `memora ingest` | Index vault (incremental by default) |
| `memora ingest --full` | Full re-index (ignore change detection) |
| `memora search <query>` | Search indexed knowledge |
| `memora check-ollama` | Check Ollama connectivity and model |
| `memora pull-model` | Pull embedding model in Ollama |
| `memora mcp` | Start MCP server (stdio) |
| `memora mcp http` | Start MCP server (HTTP) |

## MCP Tools

| Tool | Description |
|------|-------------|
| `memorize` | Capture knowledge into memory |
| `search_memory` | Hybrid search (keyword + semantic) |
| `get_context` | Retrieve relevant context for a topic |
| `list_sources` | Show indexed files |
| `reindex` | Full vault re-index |

---

## Project Structure

```
MEMORA/
├── README.md
├── LICENSE
├── requirements.txt
├── .gitignore
├── .env.example
├── config.py
├── memora/
│   ├── __init__.py
│   ├── config.py
│   ├── ingestion/
│   │   ├── __init__.py
│   │   ├── vault_reader.py
│   │   ├── chunker.py
│   │   └── indexer.py
│   ├── embeddings/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   └── ollama_provider.py
│   ├── retrieval/
│   │   ├── __init__.py
│   │   ├── keyword_search.py
│   │   ├── vector_search.py
│   │   └── hybrid_search.py
│   ├── storage/
│   │   ├── __init__.py
│   │   ├── metadata_store.py
│   │   └── vector_store.py
│   ├── memory/
│   │   ├── __init__.py
│   │   ├── capture.py
│   │   └── manager.py
│   └── mcp/
│       ├── __init__.py
│       └── server.py
├── skills/
│   └── memora/
│       └── SKILL.md
├── tests/
└── docs/
    ├── ARCHITECTURE.md
    ├── INSTALLATION.md
    └── CONFIGURATION.md
```

---

## License

MIT License — see [LICENSE](LICENSE) for details.