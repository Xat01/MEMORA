# MEMORA

> **Local-First Persistent Memory Infrastructure for AI Agents**

MEMORA is an open-source, model-independent memory infrastructure that enables AI agents to maintain persistent, searchable knowledge across sessions using Retrieval-Augmented Generation (RAG) with Obsidian Markdown as the single source of truth.

---

## ✨ Features

- **Obsidian Markdown as Source of Truth** — Your notes are never modified or altered during indexing.
- **Dual Storage & Hybrid Search** — SQLite for metadata and BM25 keyword search (FTS5), paired with ChromaDB for semantic vector embeddings via Reciprocal Rank Fusion (RRF).
- **High-Performance Batch Engine** — High-throughput indexing with SQLite WAL mode and native batch embedding generation (Ollama `/api/embed` & OpenAI batching).
- **Instant MCP Handshake (<10ms)** — Lazy-loads storage drivers on tool execution, guaranteeing instant detection and connection in Claude Desktop and other MCP clients.
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

### Option 1: Using `uv` (Recommended — Fastest)

[uv](https://github.com/astral-sh/uv) provides instant virtualenv creation and package management.

```bash
# Clone the repository
git clone https://github.com/Xat01/MEMORA.git
cd MEMORA

# Create virtual environment and install dependencies in seconds
uv venv
uv pip install -e .
```

Or install globally as an isolated CLI tool with `uv`:
```bash
uv tool install git+https://github.com/Xat01/MEMORA.git@TestRe
```

### Option 2: Using `pip`

```bash
# Install directly from Git branch
pip install git+https://github.com/Xat01/MEMORA.git@TestRe

# Or clone and install locally
git clone https://github.com/Xat01/MEMORA.git
cd MEMORA
pip install -e .
```

> **Windows Tip**: On Windows, you can always invoke MEMORA directly via the Python launcher using `py -m memora <command>` or `python -m memora <command>`.

---

## 🏁 Quick Start

### 1. Initialize Configuration
Run the automatic initialization wizard in your workspace:
```bash
# With uv:
uv run memora init

# With standard Python:
py -m memora init --vault "C:\path\to\your\Obsidian\Vault"
# (On macOS/Linux: memora init --vault "/path/to/vault")
```

If you don't pass `--vault`, MEMORA will automatically scan standard locations (Documents, Notes, etc.) and auto-detect your vault.

### 2. Choose Your Embedding Provider

Edit the generated `.env` file:

#### Option A: Local Ollama (Default, Free & Offline)
```ini
EMBEDDING_PROVIDER=ollama
EMBEDDING_MODEL=nomic-embed-text
EMBEDDING_DIMENSIONS=768
OLLAMA_HOST=http://localhost:11434
```
Ensure Ollama is running (`ollama serve`) and pull the model:
```bash
uv run memora pull-model
# or: py -m memora pull-model
```

#### Option B: OpenAI / OpenRouter / Cloud Inference
```ini
EMBEDDING_PROVIDER=openai
EMBEDDING_API_KEY=sk-...
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_DIMENSIONS=1536

# Optional: Custom endpoint (OpenRouter, Together AI, Azure, vLLM)
# EMBEDDING_API_BASE=https://openrouter.ai/api/v1
```

### 3. Verify Health
Run diagnostics to verify Python environment, database integrity, and embedding connectivity:
```bash
uv run memora doctor
# or: py -m memora doctor
```

### 4. Ingest Your Vault
Index your notes into MEMORA (processes ~1,000 chunks in a few minutes, with subsequent incremental runs taking ~1s):
```bash
uv run memora ingest
# or: py -m memora ingest
```

### 5. Test Search
Test hybrid retrieval from your terminal:
```bash
uv run memora search "cybersecurity"
# or: py -m memora search "cybersecurity"
```

---

## 🤖 Claude Desktop & MCP Integration

MEMORA exposes 5 high-level tools over the **Model Context Protocol (MCP)** via standard I/O:

* `search_memory` — Hybrid semantic + keyword search across all indexed notes.
* `get_context` — Retrieve structured context chunks for any topic.
* `memorize` — Capture new insights and summaries back into your vault.
* `list_sources` — Show all indexed files and chunk counts (unlimited).
* `reindex` — Trigger full vault re-indexing on demand.

### Configuration (`claude_desktop_config.json`)

Edit your Claude Desktop config file:
* **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`
* **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`

#### Option 1: Using `uv` (Recommended)
```json
{
  "mcpServers": {
    "memora": {
      "command": "uv",
      "args": [
        "--directory",
        "C:\\path\\to\\MEMORA",
        "run",
        "memora",
        "mcp"
      ],
      "env": {
        "VAULT_PATH": "C:\\path\\to\\your\\Obsidian\\Vault",
        "PYTHONUNBUFFERED": "1"
      }
    }
  }
}
```

#### Option 2: Using `uvx` (Zero Local Setup)
```json
{
  "mcpServers": {
    "memora": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/Xat01/MEMORA.git@TestRe",
        "memora",
        "mcp"
      ],
      "env": {
        "VAULT_PATH": "C:\\path\\to\\your\\Obsidian\\Vault",
        "PYTHONUNBUFFERED": "1"
      }
    }
  }
}
```

#### Option 3: Using Python Launcher (`py` / `python`)
```json
{
  "mcpServers": {
    "memora": {
      "command": "py",
      "args": ["-u", "-m", "memora", "mcp"],
      "env": {
        "VAULT_PATH": "C:\\path\\to\\your\\Obsidian\\Vault",
        "PYTHONUNBUFFERED": "1"
      }
    }
  }
}
```

*(On macOS/Linux, set `"command": "python3"`)*

Restart Claude Desktop, and the hammer icon will immediately turn green with all 5 memory tools ready to use.

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
SQLite (WAL + FTS5)        Embedding Provider
Metadata & Keyword         (Ollama / OpenAI / vLLM)
Search                              │
    │                               ▼
    │                           ChromaDB
    │                           Semantic Vector Search
    │                               │
    └──────────────┬────────────────┘
                   ▼
         Hybrid Search (RRF)
                   │
                   ▼
       MEMORA MCP Server (stdio)
                   │
    ┌──────────────┴──────────────┐
    ▼                             ▼
Claude Desktop              Antigravity / Cursor
```

---

## 📄 License

MIT License — see [LICENSE](LICENSE) for details.
