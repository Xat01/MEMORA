# MEMORA

> **Local-First Persistent Memory Infrastructure for AI Agents**

MEMORA is an open-source, model-independent memory infrastructure that enables AI agents to maintain persistent, searchable knowledge across sessions using Retrieval-Augmented Generation (RAG) with Obsidian Markdown as the source of truth.

---

## ✨ Features

- **Obsidian Markdown as Source of Truth** — Your notes are never modified or altered during indexing.
- **Dual Storage & Hybrid Search** — SQLite for metadata and BM25 keyword search (FTS5), paired with ChromaDB for semantic vector embeddings via Reciprocal Rank Fusion (RRF).
- **Flexible Inference & Embeddings** — Built-in support for:
  - **Local Ollama** (e.g. `nomic-embed-text`, `mxbai-embed-large`) — 100% private and offline.
  - **OpenAI-compatible APIs** (OpenAI `text-embedding-3-small`, OpenRouter, Together AI, Fireworks, Azure OpenAI).
  - **Self-hosted inference** (vLLM, LiteLLM, text-embeddings-inference, LM Studio).
  - **Custom providers** via Python subclassing.
- **Incremental Indexing** — Fast hashing detects added, modified, and deleted notes; only processes what changed.
- **Model Context Protocol (MCP)** — Exposes memory tools directly to Claude Desktop, Cursor, Antigravity, and any MCP client.
- **Security First** — Path traversal protection, zero external telemetry, local-first by design.

---

## 🚀 Installation

### One-Command Install

```bash
# Using pip
pip install git+https://github.com/Xat01/MEMORA.git@TestRe

# Or using uv (fastest)
uv tool install git+https://github.com/Xat01/MEMORA.git@TestRe

# Or using pipx
pipx install git+https://github.com/Xat01/MEMORA.git@TestRe
```

> **Windows Tip**: You can always run MEMORA reliably using `python -m memora <command>` (or `py -m memora <command>`) if your Python scripts directory isn't added to your system PATH.

---

## 🏁 Quick Start

### 1. Initialize Configuration
Run the automatic initialization wizard in your workspace:
```bash
python -m memora init
```
Or specify your Obsidian vault path directly:
```bash
python -m memora init --vault "C:\Users\you\Documents\ObsidianVault"
```
*(On macOS/Linux: `memora init --vault "/path/to/vault"`)*

### 2. Choose Your Embedding Provider

Edit your `.env` file (or set environment variables):

#### Option A: Local Ollama (Default, Free & Offline)
```ini
EMBEDDING_PROVIDER=ollama
EMBEDDING_MODEL=nomic-embed-text
EMBEDDING_DIMENSIONS=768
OLLAMA_HOST=http://localhost:11434
```
Ensure Ollama is running (`ollama serve`) and pull the model:
```bash
python -m memora pull-model
```

#### Option B: OpenAI / 3rd-Party Cloud Inference
```ini
EMBEDDING_PROVIDER=openai
EMBEDDING_API_KEY=sk-...
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_DIMENSIONS=1536
```
*(For OpenRouter, Together AI, Azure, or local vLLM, add `EMBEDDING_API_BASE=https://...`)*

### 3. Verify Health
Run diagnostics to verify Python, storage, and embedding connectivity:
```bash
python -m memora doctor
```

### 4. Ingest Your Vault
Index your notes:
```bash
python -m memora ingest
```

### 5. Test Search
Test hybrid retrieval from your terminal:
```bash
python -m memora search "machine learning concepts"
```

---

## 🤖 AI Agent & MCP Integration

MEMORA exposes tools over the **Model Context Protocol (MCP)** via standard I/O.

### Claude Desktop Integration
Add the following to your `claude_desktop_config.json`:
* **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`
* **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "memora": {
      "command": "python",
      "args": ["-m", "memora", "mcp"]
    }
  }
}
```

Restart Claude Desktop. You will now have 5 memory tools available in every chat:
- `search_memory` — Hybrid semantic + keyword search across all indexed notes.
- `get_context` — Retrieve structured context chunks for any topic.
- `memorize` — Capture new insights and summaries back into your vault.
- `list_sources` — Show indexed files and chunks.
- `reindex` — Trigger full vault re-indexing.

---

## 🛠️ CLI Commands

| Command | Description |
|---|---|
| `memora init` | Initialize configuration (`.env`) with vault auto-discovery |
| `memora doctor` | Run system diagnostics and verify connectivity |
| `memora status` | Show database statistics, files tracked, and chunk counts |
| `memora ingest` | Ingest vault (incremental by default) |
| `memora ingest --full` | Full re-index (rebuilds entire database) |
| `memora search "query"` | Search knowledge using hybrid retrieval |
| `memora check-provider` | Verify connection to configured embedding provider |
| `memora pull-model` | Download embedding model in Ollama |
| `memora mcp` | Start MCP server (stdio transport for AI clients) |

---

## 🏗️ Architecture

```
Obsidian Markdown Vault
         │
         ▼
  Vault Reader & Chunker
         │
    ┌────┴──────────────────────────┐
    ▼                               ▼
SQLite (FTS5)              Embedding Provider
Metadata & Keyword         (Ollama / OpenAI / vLLM)
Search                              │
    │                               ▼
    │                           ChromaDB
    │                           Semantic Vector Search
    └──────────────┬────────────────┘
                   ▼
         Hybrid Search (RRF)
                   │
                   ▼
          MEMORA MCP Server
                   │
    ┌──────────────┴──────────────┐
    ▼                             ▼
Claude Desktop              Antigravity / Cursor
```

---

## 📄 License

MIT License — see [LICENSE](LICENSE) for details.
