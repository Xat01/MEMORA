# MEMORA

> **Local-First Persistent Memory Infrastructure for AI Agents**

MEMORA is an open-source, model-independent memory infrastructure that enables AI agents to maintain persistent, searchable knowledge across sessions using Retrieval-Augmented Generation (RAG) with Obsidian Markdown as the source of truth.

---

## 🚀 Quick Start (Windows)

### One-Command Installation

```powershell
# 1. Open PowerShell as Administrator (recommended for PATH)
# 2. Navigate to MEMORA folder
cd C:\Users\sa595\Desktop\MEMORA

# 3. Run installer
.\install.ps1

# 4. Restart PowerShell (close and reopen)

# 5. Configure your vault
copy $env:LOCALAPPDATA\MEMORA\.env.example $env:LOCALAPPDATA\MEMORA\.env
notepad $env:LOCALAPPDATA\MEMORA\.env
# Edit VAULT_PATH to point to your Obsidian vault (folder containing .obsidian/)

# 6. Start MEMORA (starts Docker with health checks)
memora --start
```

### One-Command Installation (CMD)

```cmd
# 1. Open CMD as Administrator
cd C:\Users\sa595\Desktop\MEMORA
install.bat

# 2. Restart CMD
# 3. Configure vault
copy %LOCALAPPDATA%\MEMORA\.env.example %LOCALAPPDATA%\MEMORA\.env
notepad %LOCALAPPDATA%\MEMORA\.env
# Edit VAULT_PATH

# 4. Start MEMORA
memora --start
```

---

## ✨ Features

- **Obsidian Markdown as Source of Truth** — Original notes never modified during indexing
- **Dual Storage** — SQLite for metadata + keyword search (FTS5), ChromaDB for semantic vector search
- **Local Embeddings** — Ollama integration with provider abstraction for flexibility
- **Incremental Indexing** — Only processes changed/deleted files, avoids reprocessing
- **Hybrid Retrieval** — Combines BM25 keyword search with semantic vector search via RRF
- **MCP Server** — Exposes memory capabilities to any MCP-compatible client (Claude Desktop, etc.)
- **Security First** — Path traversal protection, no external uploads, secret protection

---

## 📋 Prerequisites

| Requirement | Version | Install |
|-------------|---------|---------|
| **Python** | 3.10+ | [python.org](https://python.org) or `winget install Python.Python.3.12` |
| **Ollama** | Latest | [ollama.ai](https://ollama.ai) |
| **Docker Desktop** | Latest | [docker.com](https://docker.com/products/docker-desktop) |

```powershell
# Verify Python
python --version
# Should show 3.10+

# Install embedding model
ollama pull nomic-embed-text
```

---

## 🎯 CLI Commands

### Lifecycle Management (Docker)

| Command | Description |
|---------|-------------|
| `memora --start` | Start with full preflight validation |
| `memora --start --skip-preflight` | Fast start (skip checks) |
| `memora --stop` | Graceful shutdown (preserves data) |
| `memora --restart` | Restart with health verification |
| `memora --status` | Show Docker, MCP, Ollama, Storage status |
| `memora --doctor` | Run system diagnostics |
| `memora --logs` | Show service logs |

### Memory Operations (Local)

| Command | Description |
|---------|-------------|
| `memora status` | Show index status |
| `memora ingest` | Index vault (incremental) |
| `memora ingest --full` | Full re-index |
| `memora search "query"` | Search knowledge |
| `memora check-ollama` | Test Ollama connection |
| `memora mcp` | Start MCP server (stdio) |

---

## 🔧 Configuration

Edit `$env:LOCALAPPDATA\MEMORA\.env`:

```env
# REQUIRED: Your Obsidian vault path
VAULT_PATH=C:\Users\you\Documents\MyVault

# Storage (usually keep defaults)
CHROMA_PATH=./data/chromadb
SQLITE_PATH=./data/memora.db

# Embeddings
EMBEDDING_MODEL=nomic-embed-text
EMBEDDING_DIMENSIONS=768
OLLAMA_HOST=http://localhost:11434

# MCP Server
MCP_TRANSPORT=http
MCP_PORT=8080
```

---

## 🤖 Claude Desktop Integration

Add to `%APPDATA%\Claude\claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "memora": {
      "command": "memora",
      "args": ["mcp"],
      "env": {
        "VAULT_PATH": "C:\\Users\\you\\Documents\\MyVault"
      }
    }
  }
}
```

Then restart Claude Desktop. Tools available:
- `memorize` — Save knowledge
- `search_memory` — Search vault
- `get_context` — Get relevant context
- `list_sources` — List indexed files
- `reindex` — Full re-index

---

## 📚 Full Documentation

| Guide | Description |
|-------|-------------|
| [INSTALLATION.md](docs/INSTALLATION.md) | Detailed install guide for all platforms |
| [CONFIGURATION.md](docs/CONFIGURATION.md) | All environment variables |
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | System design & internals |
| [DOCKER_ARCHITECTURE_DECISIONS.md](docs/DOCKER_ARCHITECTURE_DECISIONS.md) | Docker design rationale |

---

## 🛠 Troubleshooting

| Issue | Fix |
|-------|-----|
| `memora` not found | Restart terminal; check `$env:PATH -like "*MEMORA*"` |
| VAULT_PATH error | Ensure `.obsidian` folder exists at path |
| Ollama connection failed | Run `ollama serve`; verify `ollama list` |
| Docker not found | Install Docker Desktop; ensure daemon running |
| Module not found | Run `.\install.ps1` again to recreate venv |

---

## 🏗 Architecture

```
Obsidian Vault → Ingestion → SQLite (Meta + FTS5) + ChromaDB (Vectors)
                                    ↓
                            Hybrid Search (RRF)
                                    ↓
                            MCP Server → AI Agents
```

---

## 📄 License

MIT License — see [LICENSE](LICENSE) for details.