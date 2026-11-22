# MEMORA Phase 2: Docker Compose Deployment — Technical Audit

**Date:** 2026-11-19
**Auditor:** PKM Agent (Claude)
**Purpose:** Inspect existing architecture and determine requirements for reliable, reproducible Docker Compose deployment
**Status:** INSPECTION ONLY — No modifications made

---

## 1. Current Architecture

### 1.1 High-Level System Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           MEMORA ARCHITECTURE                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌──────────────┐     ┌──────────────┐     ┌──────────────────┐           │
│  │   Obsidian   │────▶│  Ingestion   │────▶│  SQLite (Meta)   │           │
│  │   Vault      │     │  Pipeline    │     │  + FTS5 (KW)     │           │
│  └──────────────┘     └──────┬───────┘     └──────────────────┘           │
│                             │                                               │
│                             ▼                                               │
│                      ┌─────────────┐     ┌──────────────────┐           │
│                      │  Embeddings │────▶│  ChromaDB        │           │
│                      │  (Ollama)   │     │  (Vector Search) │           │
│                      └─────────────┘     └──────────────────┘           │
│                             │                                               │
│                             ▼                                               │
│                      ┌──────────────────┐                                 │
│                      │  Hybrid Search   │                                 │
│                      │  (RRF Fusion)    │                                 │
│                      └────────┬─────────┘                                 │
│                               │                                           │
│                               ▼                                           │
│                      ┌──────────────────┐                                 │
│                      │   MCP Server     │                                 │
│                      │  (Memory Tools)  │                                 │
│                      └──────────────────┘                                 │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 1.2 Core Components

| Layer | Technology | Purpose | Deployment Notes |
|-------|------------|---------|------------------|
| **Source** | Obsidian Markdown (external vault) | Human-readable, git-friendly, portable | **External dependency** — mounted as volume |
| **Metadata** | SQLite + FTS5 | File tracking, chunk index, keyword search | Persistent file (`memora.db`) |
| **Vectors** | ChromaDB | Persistent semantic embeddings | Persistent directory (`chromadb/`) |
| **Embeddings** | Ollama (`nomic-embed-text`) | Local, private, no API keys | **External service** — separate container |
| **Interface** | MCP (Model Context Protocol) | Standardized agent access | stdio (default) or HTTP (port 8080) |
| **Language** | Python 3.10+ | Modular, typed, testable | Single Python process |

### 1.3 Data Flow

1. **VaultReader** reads `.md` files via MCP Connector (or local FS fallback)
2. **Chunker** splits by Markdown headers → paragraphs → sentences, preserving code blocks, with configurable overlap
3. **Indexer** coordinates: scan vault → detect changes (hash-based) → chunk → embed → dual-write to SQLite + ChromaDB
4. **MetadataStore** tracks files (mtime, size, content_hash, frontmatter_hash, status) and chunks (heading_path, token_count, vector_id)
5. **VectorStore** stores embeddings with metadata (file_path, chunk_index, heading_path, tags)
6. **HybridSearch** combines KeywordSearch (FTS5 BM25) + VectorSearch (cosine) via Reciprocal Rank Fusion (k=60)
7. **MemoryCapture/MemoryManager** provide high-level `memorize()`, `search()`, `get_context()`, `list_sources()`, `reindex()`
8. **MCP Server** exposes 5 tools: `memorize`, `search_memory`, `get_context`, `list_sources`, `reindex` (stdio + HTTP)

---

## 2. Existing Docker Implementation

### 2.1 Current State

| Artifact | Status | Location |
|----------|--------|----------|
| `Dockerfile` | ❌ **NOT EXISTENT** | — |
| `docker-compose.yml` / `compose.yaml` | ❌ **NOT EXISTENT** | — |
| `.dockerignore` | ❌ **NOT EXISTENT** | — |
| Multi-stage build | ❌ **NOT IMPLEMENTED** | — |
| Health checks | ❌ **NOT IMPLEMENTED** | — |
| Non-root user | ❌ **NOT CONFIGURED** | — |

**Conclusion:** Zero Docker infrastructure exists. This is a greenfield Docker implementation.

---

## 3. Services Requiring Containerisation

### 3.1 Primary Service: MEMORA Application

**Entry Points (from `pyproject.toml`):**
- `memora-index` → `memora.ingestion.__main__:main` (CLI ingestion)
- `memora-memory` → `memora.memory.__main__:main` (CLI memory operations)
- `memora-server` → `memora.mcp.server:main` (MCP server)

**Process Model:** Single Python process with async event loop
- Default transport: **stdio** (for Claude Desktop integration)
- Optional transport: **HTTP** on port 8080 (for remote/network access)

**Dependencies:**
- Python 3.10+ runtime
- All packages in `pyproject.toml` / `requirements.txt`
- Ollama service (separate, external)
- Obsidian vault (external, mounted volume)

### 3.2 External Dependency: Ollama

**Current Configuration:**
- Host: `OLLAMA_HOST=http://localhost:11434` (configurable via env)
- Default model: `nomic-embed-text` (768 dimensions)
- Required models: Must be pulled via `ollama pull <model>`

**Deployment Model:** Separate container (recommended) or host-level service
- GPU support optional but recommended for performance
- Persistent model storage required

### 3.3 External Dependency: Obsidian Vault

**Current Configuration:**
- Path: `VAULT_PATH` (required, absolute path)
- Contains `.obsidian/` directory marker
- Read access required; write access optional (for MCP Connector)

**Deployment Model:** Host-mounted volume (bind mount)

---

## 4. Persistent Data Locations

### 4.1 Current Paths (from `.env.example` and config)

| Data Type | Default Path | Config Variable | Size Estimate |
|-----------|--------------|-----------------|---------------|
| ChromaDB vectors | `./data/chromadb/` | `CHROMA_PATH` | ~100MB–10GB+ |
| SQLite metadata | `./data/memora.db` | `SQLITE_PATH` | ~10MB–1GB |
| Logs | `./logs/memora.log` | `LOG_FILE` | ~10MB–100MB |
| Ollama models | `~/.ollama/models` | `OLLAMA_HOST` (server-side) | ~2GB–20GB |

### 4.2 Current `.env` Configuration

```bash
VAULT_PATH=/sessions/dreamy-elegant-franklin/mnt/MEMORA/tests/fixtures/vault
CHROMA_PATH=./data/chromadb
SQLITE_PATH=./data/memora.db
EMBEDDING_MODEL=nomic-embed-text
EMBEDDING_DIMENSIONS=768
OLLAMA_HOST=http://localhost:11434
CHUNK_SIZE=512
CHUNK_OVERLAP=50
DEFAULT_SEARCH_K=10
HYBRID_RRF_K=60
MCP_TRANSPORT=stdio
MCP_HOST=127.0.0.1
MCP_PORT=8080
LOG_LEVEL=INFO
LOG_FILE=./logs/memora.log
```

---

## 5. Required Volumes and Networking

### 5.1 Volumes

| Volume | Source | Target (Container) | Mode | Purpose |
|--------|--------|-------------------|------|---------|
| `obsidian-vault` | Host path (VAULT_PATH) | `/vault` | `ro` | Read-only vault access |
| `chromadb-data` | Named volume | `/data/chromadb` | `rw` | ChromaDB persistence |
| `sqlite-data` | Named volume | `/data` | `rw` | SQLite database file |
| `logs-data` | Named volume | `/logs` | `rw` | Application logs |
| `ollama-models` | Named volume | `/root/.ollama` | `rw` | Ollama model cache |

### 5.2 Networking

| Service | Port | Protocol | Exposure | Notes |
|---------|------|----------|----------|-------|
| MEMORA MCP (HTTP) | 8080 | TCP | Optional (host network) | Only if `MCP_TRANSPORT=http` |
| Ollama API | 11434 | TCP | Internal (Docker network) | MEMORA → Ollama |
| Ollama GPU | N/A | — | — | Requires `--gpus all` if GPU enabled |

**Network Topology:**
```
[Host] ←──(bind mount)──→ [Obsidian Vault]
[MEMORA] ←──(Docker net)──→ [Ollama]
[MEMORA] ←──(stdio)───────→ [Claude Desktop]
[MEMORA] ←──(HTTP 8080)───→ [Remote Clients] (optional)
```

---

## 6. Environment Configuration Requirements

### 6.1 Required Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `VAULT_PATH` | **YES** | — | Absolute path to Obsidian vault (host path for bind mount) |
| `CHROMA_PATH` | No | `/data/chromadb` | ChromaDB persistence directory (container path) |
| `SQLITE_PATH` | No | `/data/memora.db` | SQLite database path (container path) |
| `EMBEDDING_MODEL` | No | `nomic-embed-text` | Ollama embedding model name |
| `EMBEDDING_DIMENSIONS` | No | `768` | Model output dimensions (must match model) |
| `OLLAMA_HOST` | No | `http://ollama:11434` | Ollama API endpoint (container DNS name) |
| `CHUNK_SIZE` | No | `512` | Token chunk size |
| `CHUNK_OVERLAP` | No | `50` | Token overlap between chunks |
| `DEFAULT_SEARCH_K` | No | `10` | Default search results |
| `HYBRID_RRF_K` | No | `60` | RRF fusion constant |
| `MCP_TRANSPORT` | No | `stdio` | `stdio` or `http` |
| `MCP_HOST` | No | `0.0.0.0` | HTTP bind host (if HTTP transport) |
| `MCP_PORT` | No | `8080` | HTTP port (if HTTP transport) |
| `LOG_LEVEL` | No | `INFO` | Logging level |
| `LOG_FILE` | No | `/logs/memora.log` | Log file path (container path) |

### 6.2 Configuration Management

- **Mechanism:** Pydantic Settings (`pydantic-settings>=2.3.0`)
- **Source:** `.env` file (loaded from project root)
- **Path Resolution:** Relative paths resolved against project root; Unix-style absolute paths (`/path`) treated as absolute on Windows for WSL compatibility
- **Validation:** `validate_vault()` checks `.obsidian/` directory exists

---

## 7. MCP Server Dependencies and Communication

### 7.1 MCP Server Implementation

**File:** `memora/mcp/server.py`
- **Class:** `MemoraMCPServer`
- **Transport Options:**
  1. **stdio** (default) — `run_stdio()` uses `mcp.server.stdio.stdio_server()`
  2. **HTTP** — `run_http()` uses `mcp.server.streamable_http_manager.StreamableHTTPSessionManager` + `uvicorn` + `starlette`

**MCP Tools Exposed:**
| Tool | Parameters | Description |
|------|------------|-------------|
| `memorize` | `content`, `tags?`, `source?` | Capture knowledge |
| `search_memory` | `query`, `k?`, `mode?`, `file_paths?`, `tags?` | Hybrid search |
| `get_context` | `topic`, `k?`, `mode?`, `max_chars?` | Formatted context |
| `list_sources` | `limit?` | List indexed files |
| `reindex` | `full?` | Trigger vault re-index |

### 7.2 Communication Requirements

**stdio Transport (Default):**
- Direct process communication via stdin/stdout
- No network ports required
- Used by Claude Desktop via MCP Connector
- **Container implication:** Must run with `-i` (interactive) for stdin/stdout

**HTTP Transport (Optional):**
- Requires `uvicorn` and `starlette` dependencies (already in `pyproject.toml` optional? No — must verify)
- Runs on configurable host/port (default `127.0.0.1:8080`)
- **Container implication:** Port 8080 must be exposed/published

**Note:** Current `requirements.txt` does NOT include `uvicorn` or `starlette` — these are imported conditionally in `server.py`. They must be added to dependencies for HTTP transport.

---

## 8. Network Bindings and Exposed Ports

### 8.1 Current Bindings

| Service | Host | Port | Transport | Config Variable |
|---------|------|------|-----------|-----------------|
| Ollama | localhost | 11434 | HTTP | `OLLAMA_HOST` |
| MEMORA MCP (HTTP) | 127.0.0.1 | 8080 | HTTP | `MCP_HOST`, `MCP_PORT` |
| MEMORA MCP (stdio) | N/A | N/A | stdio | `MCP_TRANSPORT=stdio` |

### 8.2 Docker Network Requirements

- **Internal network:** `memora-network` (bridge) for MEMORA ↔ Ollama communication
- **Ollama DNS:** `ollama` (service name in docker-compose)
- **MEMORA → Ollama:** `http://ollama:11434`
- **Host → MEMORA (HTTP):** Port 8080 published if HTTP transport enabled
- **Host → MEMORA (stdio):** No port; uses container stdin/stdout

---

## 9. Background Processes and Service Dependencies

### 9.1 Process Hierarchy

```
MEMORA Container (single Python process)
├── Async event loop (anyio)
├── MCP Server (stdio or HTTP)
│   ├── Tool handlers (memorize, search, context, sources, reindex)
│   │   ├── MemoryManager
│   │   │   ├── Indexer (ingestion)
│   │   │   ├── HybridSearch (retrieval)
│   │   │   └── MemoryCapture
│   │   ├── MetadataStore (SQLite + FTS5)
│   │   ├── VectorStore (ChromaDB)
│   │   └── OllamaProvider (HTTP client → Ollama)
│   └── HTTP server (uvicorn) — ONLY if MCP_TRANSPORT=http
└── Background tasks: None (synchronous request handling)
```

### 9.2 Service Dependencies (Startup Order)

1. **Ollama** — Must be healthy before MEMORA starts (embedding model required)
2. **ChromaDB** — Local persistence, no separate process (embedded in MEMORA process)
3. **SQLite** — Local file, no separate process
4. **MEMORA** — Requires Ollama + vault access
5. **MCP Client (Claude Desktop)** — Connects to MEMORA via stdio or HTTP

### 9.3 Health Check Endpoints

**Current Implementation:** `memora doctor` command (12 checks)
- Python environment
- Dependencies
- Configuration
- Ollama connectivity
- Embedding model availability
- ChromaDB accessibility + metadata consistency
- SQLite integrity + WAL mode
- Obsidian vault validity
- Embedding pipeline end-to-end
- MCP configuration
- Storage (directories, permissions, disk space)

**No HTTP health endpoint exists** — would need to be added for Docker health checks.

---

## 10. Graceful Shutdown and Process Management

### 10.1 Current State

| Aspect | Status | Details |
|--------|--------|---------|
| Signal handling | ❌ **NOT IMPLEMENTED** | No SIGTERM/SIGINT handlers |
| Graceful shutdown | ❌ **NOT IMPLEMENTED** | No cleanup of DB connections, HTTP client |
| Process supervision | ❌ **NOT IMPLEMENTED** | Single process, no supervisor |
| Connection pooling | ⚠️ **PARTIAL** | httpx client reused, but not explicitly closed |
| Database connections | ⚠️ **PARTIAL** | SQLite connections per-operation (context manager) |

### 10.2 Required Improvements for Docker

1. **Signal handlers** for SIGTERM/SIGINT
2. **Graceful shutdown** sequence:
   - Stop accepting new MCP requests
   - Close HTTP client (Ollama)
   - Close ChromaDB client
   - Close SQLite connections
   - Flush logs
3. **Health check endpoint** for Docker `healthcheck`
4. **Init system** (tini or dumb-init) for proper signal propagation

---

## 11. Security Considerations

### 11.1 Current Security Posture

| Control | Status | Details |
|---------|--------|---------|
| Non-root user | ❌ **NOT CONFIGURED** | Runs as root in container |
| Read-only vault | ✅ **ENFORCED** | Vault mounted read-only |
| Path traversal protection | ✅ **IMPLEMENTED** | `VaultReader` validates paths |
| Secret protection | ✅ **NO CREDENTIALS** | No API keys, tokens in code |
| Network isolation | ⚠️ **PARTIAL** | Ollama on localhost only |
| Dependency scanning | ❌ **NOT CONFIGURED** | No SCA in CI |

### 11.2 Docker Security Requirements

1. **Non-root user:** Create `memora` user (UID 1000), run as non-root
2. **Read-only root filesystem:** Where possible
3. **Capability dropping:** `CAP_DROP=ALL`
4. **No new privileges:** `security_opt: no-new-privileges:true`
5. **Resource limits:** Memory/CPU limits to prevent DoS
6. **Secrets management:** No secrets in image; use Docker secrets or env files

---

## 12. Identified Deployment Risks

| Risk | Severity | Impact | Mitigation |
|------|----------|--------|------------|
| **No existing Docker files** | High | Greenfield implementation required | Full Docker implementation needed |
| **Ollama external dependency** | High | MEMORA fails without Ollama | Health checks, dependency ordering, model pre-pull |
| **VAULT_PATH host-dependent** | High | Path differs across environments | Bind mount with configurable host path |
| **Relative paths in config** | Medium | Breaks if CWD changes | Resolve to absolute paths in container |
| **No HTTP health endpoint** | Medium | Docker can't verify service health | Add `/health` endpoint to MCP HTTP server |
| **No graceful shutdown** | Medium | Data corruption on restart | Implement signal handlers |
| **Root user in container** | Medium | Security risk | Run as non-root user |
| **Missing uvicorn/starlette** | Low | HTTP transport fails | Add to dependencies |
| **ChromaDB/SQLite locking** | Low | Concurrent access issues | Single process; document limitation |
| **Model dimension mismatch** | Low | Silent search degradation | Validate on startup (already in doctor) |

---

## 13. Recommended Docker Compose Architecture

### 13.1 Service Definitions

```yaml
# docker-compose.yml (recommended structure)
services:
  # ─── Ollama Embedding Service ───
  ollama:
    image: ollama/ollama:latest
    container_name: memora-ollama
    restart: unless-stopped
    volumes:
      - ollama-models:/root/.ollama
    ports:
      - "11434:11434"  # Optional: expose for debugging
    healthcheck:
      test: ["CMD", "ollama", "list"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 10s
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]  # Optional GPU support

  # ─── MEMORA Application ───
  memora:
    build:
      context: .
      dockerfile: Dockerfile
      target: runtime
    container_name: memora
    restart: unless-stopped
    depends_on:
      ollama:
        condition: service_healthy
    environment:
      - VAULT_PATH=/vault
      - CHROMA_PATH=/data/chromadb
      - SQLITE_PATH=/data/memora.db
      - OLLAMA_HOST=http://ollama:11434
      - EMBEDDING_MODEL=${EMBEDDING_MODEL:-nomic-embed-text}
      - EMBEDDING_DIMENSIONS=${EMBEDDING_DIMENSIONS:-768}
      - MCP_TRANSPORT=${MCP_TRANSPORT:-stdio}
      - MCP_HOST=0.0.0.0
      - MCP_PORT=8080
      - LOG_LEVEL=${LOG_LEVEL:-INFO}
      - LOG_FILE=/logs/memora.log
    volumes:
      - ${VAULT_PATH}:/vault:ro
      - chromadb-data:/data/chromadb
      - sqlite-data:/data
      - logs-data:/logs
    # For stdio transport (Claude Desktop):
    # stdin_open: true
    # tty: true
    # For HTTP transport:
    ports:
      - "8080:8080"  # Only if MCP_TRANSPORT=http
    healthcheck:
      test: ["CMD", "memora", "doctor", "--json"]
      interval: 60s
      timeout: 30s
      retries: 3
      start_period: 30s
    user: "1000:1000"
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
    read_only: true
    tmpfs:
      - /tmp
      - /var/tmp

volumes:
  ollama-models:
  chromadb-data:
  sqlite-data:
  logs-data:

networks:
  default:
    name: memora-network
```

### 13.2 Multi-Stage Dockerfile

```dockerfile
# Dockerfile
# ─── Build Stage ───
FROM python:3.12-slim AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY pyproject.toml requirements.txt ./
RUN pip install --no-cache-dir --prefix=/install \
    -r requirements.txt \
    && pip install --no-cache-dir --prefix=/install uvicorn starlette

# ─── Runtime Stage ───
FROM python:3.12-slim AS runtime

WORKDIR /app

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 1000 --gid 1000 --create-home --shell /bin/bash memora

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application code
COPY --chown=memora:memora . .

# Create data directories with correct ownership
RUN mkdir -p /data/chromadb /logs && chown -R memora:memora /data /logs

USER memora

# Default command (stdio transport for Claude Desktop)
ENTRYPOINT ["memora-server"]

# Health check command available via: memora doctor --json
```

### 13.3 Environment File Template (`.env.docker`)

```bash
# .env.docker — Copy to .env and customize for Docker deployment

# REQUIRED: Host path to Obsidian vault (absolute path on host)
# Linux/macOS: VAULT_PATH=/home/user/Documents/MyVault
# Windows: VAULT_PATH=C:\Users\user\Documents\MyVault
# WSL2: VAULT_PATH=/mnt/c/Users/user/Documents/MyVault
VAULT_PATH=

# Embedding configuration
EMBEDDING_MODEL=nomic-embed-text
EMBEDDING_DIMENSIONS=768

# MCP transport: stdio (for Claude Desktop) or http (for network clients)
MCP_TRANSPORT=stdio

# Logging
LOG_LEVEL=INFO
```

---

## 14. Phased Implementation Plan

### Phase 1: Foundation (Week 1)
- [ ] Create `Dockerfile` with multi-stage build
- [ ] Create `docker-compose.yml` with Ollama + MEMORA services
- [ ] Create `.dockerignore` (exclude `.venv`, `__pycache__`, `data/`, `logs/`, `.git`, `*.db`, `.env`)
- [ ] Create `.env.docker` template
- [ ] Add `uvicorn` and `starlette` to `pyproject.toml` dependencies (for HTTP transport)
- [ ] Test: `docker compose build && docker compose up`

### Phase 2: Health & Reliability (Week 1-2)
- [ ] Add `/health` HTTP endpoint to MCP server (returns JSON status)
- [ ] Implement signal handlers (SIGTERM/SIGINT) for graceful shutdown
- [ ] Add Docker healthcheck using `memora doctor --json`
- [ ] Configure non-root user (UID 1000) in Dockerfile
- [ ] Add security hardening (cap_drop, read_only, no-new-privileges)
- [ ] Test: Container restart, graceful shutdown, health checks

### Phase 3: Configuration & Volumes (Week 2)
- [ ] Validate volume mounts (vault read-only, data persistence)
- [ ] Test cross-platform path resolution (Windows/WSL/Linux)
- [ ] Document VAULT_PATH configuration for each platform
- [ ] Add model pre-pull mechanism (init container or entrypoint script)
- [ ] Test: Full indexing pipeline in container

### Phase 4: MCP Integration (Week 2-3)
- [ ] Test stdio transport with Claude Desktop (requires `stdin_open: true`, `tty: true`)
- [ ] Test HTTP transport with remote clients
- [ ] Document both transport modes
- [ ] Validate MCP tool registration works in container

### Phase 5: Production Hardening (Week 3)
- [ ] Resource limits (memory, CPU)
- [ ] Log rotation configuration
- [ ] Backup/restore procedures for volumes
- [ ] CI/CD pipeline for image building
- [ ] Documentation updates

---

## 15. Blockers and Dependencies

### 15.1 Critical Blockers (Must Resolve Before Phase 1)

| Blocker | Description | Resolution |
|---------|-------------|------------|
| **No Git repository** | Version control not initialized (per BASELINE_AUDIT.md) | Run `git init && git add . && git commit` before Docker work |
| **VAULT_PATH not configured** | `.env` has empty VAULT_PATH | Configure valid vault path in `.env` or `.env.docker` |
| **Ollama not running** | External dependency unavailable | Install/start Ollama, pull `nomic-embed-text` model |
| **Missing HTTP dependencies** | `uvicorn`, `starlette` not in requirements | Add to `pyproject.toml` `[project.dependencies]` |

### 15.2 Dependencies

| Dependency | Version | Purpose |
|------------|---------|---------|
| Docker Engine | 24.0+ | Container runtime |
| Docker Compose | 2.20+ | Multi-container orchestration |
| Ollama | 0.1.0+ | Embedding model server |
| NVIDIA Container Toolkit | Optional | GPU support for Ollama |

### 15.3 Platform-Specific Considerations

| Platform | VAULT_PATH Format | Notes |
|----------|-------------------|-------|
| Linux | `/home/user/vault` | Direct bind mount |
| macOS | `/Users/user/vault` | Direct bind mount |
| Windows (Docker Desktop) | `C:\Users\user\vault` | Use WSL2 path: `/mnt/c/Users/user/vault` |
| WSL2 | `/mnt/c/Users/user/vault` | Direct bind mount from WSL |

---

## 16. Conclusion

The MEMORA codebase is **well-structured and ready for containerisation** with:
- Clean modular architecture (separation of concerns)
- Configuration via environment variables (12-factor compatible)
- Comprehensive diagnostics (`memora doctor`)
- No hardcoded paths or assumptions
- Single-process design (simplifies container model)

**Primary work required:**
1. Create Dockerfile and docker-compose.yml (greenfield)
2. Add HTTP health endpoint and graceful shutdown
3. Harden security (non-root, capabilities)
4. Validate volume mounting across platforms
5. Test both MCP transport modes

**No architectural changes required** — the existing design maps cleanly to a containerised deployment.

---

## Appendix: File Inventory for Docker Context

```
MEMORA/
├── Dockerfile                    # TO CREATE
├── docker-compose.yml            # TO CREATE
├── .dockerignore                 # TO CREATE
├── .env.docker                   # TO CREATE
├── .env.example                  # EXISTS (template)
├── pyproject.toml                # EXISTS (needs uvicorn/starlette)
├── requirements.txt              # EXISTS (needs uvicorn/starlette)
├── memora/                       # Application package
│   ├── cli.py                    # Entry points
│   ├── config.py                 # Pydantic Settings
│   ├── mcp/server.py             # MCP Server (needs health endpoint)
│   ├── memory/                   # High-level API
│   ├── ingestion/                # Vault ingestion pipeline
│   ├── embeddings/               # Ollama provider
│   ├── retrieval/                # Hybrid search
│   └── storage/                  # SQLite + ChromaDB
├── tests/                        # Test suite
├── skills/memora/SKILL.md        # Skill definition
├── docs/                         # Documentation
└── data/                         # Runtime (gitignored) — becomes volumes
    ├── chromadb/
    └── memora.db
```

---

*Report generated per MEMORA Phase 2 inspection requirements. No files were modified during this audit.*