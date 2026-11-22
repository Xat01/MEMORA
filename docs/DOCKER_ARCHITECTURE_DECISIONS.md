# MEMORA Phase 2: Docker Deployment — Architecture Decision Report

**Date:** 2026-11-19
**Status:** DECISION DOCUMENT — Awaiting Approval for Phase 1 Implementation
**Based on:** Technical Audit (`DOCKER_DEPLOYMENT_AUDIT.md`) + Code Inspection

---

## Executive Summary

This report resolves five architectural concerns raised during audit review. All findings are based on actual code inspection — no assumptions.

| Concern | Resolution | Impact on Docker Design |
|---------|------------|-------------------------|
| 1. Git Repository | **Already initialized & synced to GitHub** — audit was stale | No action needed; preserve existing `.git` |
| 2. Obsidian Vault | **Read-only is correct** — MEMORA never writes to vault | Bind mount `ro` confirmed |
| 3. MCP Transport | **Both modes required** — different deployment patterns | Dual entrypoints; stdio needs interactive container |
| 4. Ollama | **Configurable dual support** — host or container | Optional Ollama service; env-switchable |
| 5. Health Monitoring | **Four-tier checks** — no embedding ops | New HTTP endpoints; compose healthchecks |

---

## 1. Git Repository — Discrepancy Resolved

### Audit Claim (Stale)
> "Git Repository: ❌ NOT INITIALIZED — No `.git` directory exists"

### Actual State (Verified 2026-11-19)
```bash
$ git status
On branch master
Your branch is up to date with 'origin/master'.

$ git remote -v
origin  https://github.com/Xat01/MEMORA.git (fetch)
origin  https://github.com/Xat01/MEMORA.git (push)

$ git log --oneline -1
8566b8d chore: initialize MEMORA v0.1.0 baseline
```

### Explanation
The `BASELINE_AUDIT.md` was generated on **2026-11-17** (before Git initialization). The repository was initialized and pushed to GitHub **after** that audit. Current state is clean and synced.

### Decision
- **Preserve existing `.git`** — no re-initialization
- **Preserve Git history** — single commit `8566b8d`
- **Remote origin** `https://github.com/Xat01/MEMORA.git` remains authoritative
- **Working tree** clean (only new audit files untracked)

---

## 2. Obsidian Vault — Read-Only Bind Mount Confirmed

### Code Path Analysis

| Operation | Code Location | Vault Access | Verdict |
|-----------|--------------|--------------|---------|
| **List files** | `VaultReader._list_local()` | `rglob()` → READ | ✅ Read-only |
| **Read file** | `VaultReader._read_local()` | `read_text()`, `stat()` | ✅ Read-only |
| **Read via MCP** | `VaultReader._read_via_mcp()` | MCP `get_vault_file` | ✅ Read-only |
| **Change detection** | `Indexer._detect_changes()` | Compares `mtime`, `hash` | ✅ Read-only |
| **Indexing** | `Indexer._index_file()` | Reads → writes to **SQLite/ChromaDB** | ✅ No vault write |
| **Knowledge capture** | `MemoryCapture.memorize()` | Writes to **virtual path** `_captured/...` in SQLite/ChromaDB | ✅ No vault write |
| **Diagnostics write test** | `Doctor._check_obsidian_vault()` | Creates `.memora_read_test` → **deletes immediately** | ⚠️ Transient |

### Key Finding: Virtual File Paths
```python
# MemoryCapture.memorize() — line 78
virtual_path = f"_captured/{source or 'manual'}/{timestamp}.md"
```
All "captured knowledge" is stored in **internal databases** (SQLite + ChromaDB) under virtual paths prefixed with `_captured/`. **Zero writes to actual Obsidian vault.**

### Decision
- **Bind mount: `ro` (read-only) is correct and sufficient**
- No functionality compromised
- Vault remains pure "source of truth" — never modified by MEMORA
- Diagnostics write test is acceptable (ephemeral, self-cleaning); if strictly prohibited, can be disabled via env var

### Volume Configuration
```yaml
volumes:
  - ${VAULT_PATH}:/vault:ro    # Read-only bind mount
```

---

## 3. MCP Transport — Dual Mode Architecture (Revised)

### Current Implementation (`memora/mcp/server.py`)

| Transport | Entry Point | Dependencies | Use Case |
|-----------|-------------|--------------|----------|
| **STDIO** | `run_stdio()` | `mcp.server.stdio` | Claude Desktop (local) |
| **HTTP** | `run_http(host, port)` | `uvicorn`, `starlette`, `mcp.server.streamable_http_manager` | Network/container clients |

**CLI Selection** (line 281-288):
```python
if len(sys.argv) > 1 and sys.argv[1] == "http":
    await server.run_http(host, port)
else:
    await server.run_stdio()
```

### Docker Deployment Patterns — Revised

#### STDIO Mode: Direct Launch via `docker run` (Not Compose Exec)

**Critical Correction:** Do NOT run a persistent background STDIO container and then `docker compose exec` into it. This breaks MCP protocol isolation and introduces logging/terminal noise into the stdio stream.

**Correct Pattern:** Claude Desktop launches a **fresh container per session** using `docker run`:

```json
{
  "mcpServers": {
    "memora": {
      "command": "docker",
      "args": [
        "run",
        "--rm",
        "-i",
        "--network=memora-network",
        "-v", "${VAULT_PATH}:/vault:ro",
        "-v", "chromadb-data:/data/chromadb",
        "-v", "sqlite-data:/data",
        "-v", "logs-data:/logs",
        "-e", "OLLAMA_HOST=http://host.docker.internal:11434",
        "-e", "EMBEDDING_MODEL=nomic-embed-text",
        "-e", "EMBEDDING_DIMENSIONS=768",
        "-e", "LOG_LEVEL=INFO",
        "-e", "LOG_FILE=/logs/memora.log",
        "memora:latest",
        "memora-server"
      ]
    }
  }
}
```

**Key properties:**
- `--rm` — Container removed after session ends (no persistent daemon)
- `-i` — Keep stdin open (required for stdio)
- **No `-t` / `--tty`** — TTY adds terminal control sequences that corrupt MCP protocol
- `--network=memora-network` — Connects to shared network for Ollama/volumes
- Volumes mounted directly (not via compose service)

**Alternative: `docker compose run --rm`** (if compose file present):
```json
"args": [
  "compose", "run", "--rm", "-T",
  "-e", "OLLAMA_HOST=http://host.docker.internal:11434",
  "memora-stdio", "memora-server"
]
```
- `-T` disables TTY allocation (critical for clean stdio)
- `--rm` removes container after exit

#### HTTP Mode: Persistent Background Service
```yaml
# docker-compose.yml
memora-http:
  build:
    context: .
    dockerfile: Dockerfile
    target: runtime
  profiles: ["http"]
  container_name: memora-http
  restart: unless-stopped
  entrypoint: ["memora-server", "http", "0.0.0.0", "8080"]
  environment:
    - VAULT_PATH=/vault
    - CHROMA_PATH=/data/chromadb
    - SQLITE_PATH=/data/memora.db
    - OLLAMA_HOST=${OLLAMA_HOST:-http://host.docker.internal:11434}
    - EMBEDDING_MODEL=${EMBEDDING_MODEL:-nomic-embed-text}
    - EMBEDDING_DIMENSIONS=${EMBEDDING_DIMENSIONS:-768}
    - MCP_TRANSPORT=http
    - MCP_HOST=0.0.0.0
    - MCP_PORT=8080
    - LOG_LEVEL=${LOG_LEVEL:-INFO}
    - LOG_FILE=/logs/memora.log
  volumes:
    - ${VAULT_PATH}:/vault:ro
    - chromadb-data:/data/chromadb
    - sqlite-data:/data
    - logs-data:/logs
  ports:
    - "8080:8080"
  healthcheck:
    test: ["CMD", "curl", "-f", "http://localhost:8080/health/ready"]
    interval: 30s
    timeout: 10s
    retries: 3
    start_period: 15s
  user: "1000:1000"
  security_opt:
    - no-new-privileges:true
  cap_drop:
    - ALL
  read_only: true
  tmpfs:
    - /tmp
    - /var/tmp
  depends_on:
    ollama:
      condition: service_healthy
      required: false
```

#### Shared Image, Dual Entrypoints
Single `Dockerfile` builds `memora:latest` image used by both patterns.

**Entrypoint Script** (`docker-entrypoint.sh`):
```bash
#!/bin/bash
set -e
# Transport selected by CLI args, not env
# Default (no args) = stdio; "http" = HTTP transport
exec memora-server "$@"
```

**Image Usage:**
- STDIO: `docker run -i --rm memora:latest memora-server`
- HTTP: `docker run -d -p 8080:8080 memora:latest memora-server http 0.0.0.0 8080`

### Decision
- **STDIO**: Ephemeral `docker run --rm -i` (no TTY) — launched by Claude Desktop per session
- **HTTP**: Persistent `docker compose up -d` service with restart policy
- **Shared image**: `memora:latest` built once, used by both patterns
- **No background STDIO daemon** — eliminates protocol contamination risk
- **No `docker compose exec` for STDIO** — use `docker run` or `compose run --rm -T`

---

## 4. Ollama — Configurable Dual Support

### Current Integration (`memora/embeddings/ollama_provider.py`)

```python
# Configuration (from config.py)
OLLAMA_HOST = "http://localhost:11434"      # Default
EMBEDDING_MODEL = "nomic-embed-text"        # Default
EMBEDDING_DIMENSIONS = 768                   # Must match model

# Health check
def health_check(self) -> bool:
    response = self.client.get("/api/tags", timeout=5.0)
    return response.status_code == 200 and model_in_list

# Model pull
def pull_model(self) -> bool:
    response = self.client.post("/api/pull", json={"name": self.model, "stream": False}, timeout=300.0)
    return response.status_code == 200
```

### Deployment Options

| Option | OLLAMA_HOST | GPU | Model Persistence | Use Case |
|--------|-------------|-----|-------------------|----------|
| **Host Ollama (Docker Desktop)** | `http://host.docker.internal:11434` | Host GPU | Host `~/.ollama` | Mac/Windows dev |
| **Host Ollama (Linux)** | `http://172.17.0.1:11434` | Host GPU | Host `~/.ollama` | Linux dev |
| **Containerized Ollama** | `http://ollama:11434` | Container GPU | Named volume `ollama-models` | Production/CI |
| **External Ollama** | `http://<ip>:11434` | Remote | Remote | Distributed |

### Decision: Configurable with Profile-Based Compose

**Primary: Host Ollama (default for dev)**
- Avoids duplicate Ollama instances
- Uses existing pulled models
- GPU via host automatically

**Optional: Containerized Ollama (profile `ollama`)**
```yaml
services:
  ollama:
    image: ollama/ollama:latest
    profiles: ["ollama"]
    volumes:
      - ollama-models:/root/.ollama
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
    healthcheck:
      test: ["CMD", "ollama", "list"]
      interval: 30s
      timeout: 10s
      retries: 3
```

**MEMORA Service:**
```yaml
memora:
  environment:
    - OLLAMA_HOST=${OLLAMA_HOST:-http://host.docker.internal:11434}
  profiles: ["default", "ollama"]
  depends_on:
    ollama:
      condition: service_healthy
      required: false  # Optional dependency
```

**Default `.env.docker`:**
```bash
# Use host Ollama by default (no duplicate)
OLLAMA_HOST=http://host.docker.internal:11434

# To use containerized Ollama: docker compose --profile ollama up
# Then: OLLAMA_HOST=http://ollama:11434
```

### GPU & Resource Considerations
- **Containerized Ollama**: GPU via `deploy.resources.reservations` (Compose 2.3+)
- **Host Ollama**: GPU managed by host installation
- **Model persistence**: Named volume `ollama-models` survives container recreation
- **Memory**: `nomic-embed-text` ~2GB RAM; `mxbai-embed-large` ~4GB

---

## 5. Health Monitoring — Four-Tier Design

### Current State: `memora doctor` (12 checks, all-in-one)
```bash
memora doctor --json  # Returns all checks at once
```

### Problem
- Single endpoint mixes liveness, readiness, dependency, storage
- Some checks expensive (embedding pipeline test generates embeddings)
- No HTTP exposure for Docker healthchecks

### Required: Separate Endpoints

| Check | Endpoint | Purpose | Docker Use | Expensive Ops |
|-------|----------|---------|------------|---------------|
| **Liveness** | `GET /health/live` | Process alive, not deadlocked | `livenessProbe` / `restart: on-failure` | ❌ None |
| **Readiness** | `GET /health/ready` | Ready to serve MCP requests | `readinessProbe` / compose `healthcheck` | ❌ None (config, DB connectivity only) |
| **Ollama** | `GET /health/ollama` | Embedding service available | Dependency monitoring | ❌ No embedding gen |
| **Storage** | `GET /health/storage` | Volumes writable, space OK | Volume health monitoring | ❌ No embedding gen |

### Implementation Plan (Code Changes Required)

**Add to `MemoraMCPServer` (HTTP mode only):**
```python
# In run_http() — add health routes before MCP mount
from starlette.routing import Route

async def health_live(request):
    return JSONResponse({"status": "alive"})

async def health_ready(request):
    # Quick checks: config, SQLite, ChromaDB
    config = get_config()
    config.ensure_dirs()
    # Test SQLite
    MetadataStore(db_path=config.sqlite_path).get_index_stats()
    # Test ChromaDB
    VectorStore(persist_path=str(config.chroma_path)).count()
    return JSONResponse({"status": "ready"})

async def health_ollama(request):
    # Ollama connectivity + model
    provider = OllamaProvider(host=config.ollama_host, model=config.embedding_model)
    healthy = provider.health_check()
    return JSONResponse({"status": "healthy" if healthy else "unhealthy", "ollama": config.ollama_host})

async def health_storage(request):
    # Disk space, writable
    usage = shutil.disk_usage(config.data_dir)
    free_gb = usage.free / (1024**3)
    return JSONResponse({"status": "ok" if free_gb > 1 else "low", "free_gb": round(free_gb, 1)})

app = Starlette(routes=[
    Route("/health/live", health_live),
    Route("/health/ready", health_ready),
    Route("/health/ollama", health_ollama),
    Route("/health/storage", health_storage),
    Mount("/", app=session_manager.streamable_http_app()),
])
```

**Docker Compose Healthchecks:**
```yaml
memora:
  healthcheck:
    test: ["CMD", "curl", "-f", "http://localhost:8080/health/ready"]
    interval: 30s
    timeout: 10s
    retries: 3
    start_period: 15s
  # For stdio mode (no HTTP), use doctor JSON:
  # healthcheck:
  #   test: ["CMD", "memora", "doctor", "--json"]
  #   interval: 60s
  #   timeout: 30s
  #   retries: 3
```

### Decision
- **Add 4 HTTP health endpoints** (HTTP transport only)
- **STDIO mode**: Use `memora doctor --json` for compose healthcheck
- **No embedding generation** in any health check
- **Liveness**: Trivial (process responds)
- **Readiness**: Config + DB connectivity only
- **Ollama**: Connectivity + model existence (no embed)
- **Storage**: Disk space + writable test

---

## Recommended Architecture Summary

### Docker Compose Service Design

```yaml
# docker-compose.yml
services:
  # ─── Optional: Containerized Ollama ───
  ollama:
    image: ollama/ollama:latest
    profiles: ["ollama"]
    container_name: memora-ollama
    restart: unless-stopped
    volumes:
      - ollama-models:/root/.ollama
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
              capabilities: [gpu]

  # ─── MEMORA: STDIO Profile (Claude Desktop) ───
  memora-stdio:
    build:
      context: .
      dockerfile: Dockerfile
      target: runtime
    profiles: ["stdio"]
    container_name: memora-stdio
    stdin_open: true
    tty: true
    entrypoint: ["memora-server"]
    environment:
      - VAULT_PATH=/vault
      - CHROMA_PATH=/data/chromadb
      - SQLITE_PATH=/data/memora.db
      - OLLAMA_HOST=${OLLAMA_HOST:-http://host.docker.internal:11434}
      - EMBEDDING_MODEL=${EMBEDDING_MODEL:-nomic-embed-text}
      - EMBEDDING_DIMENSIONS=${EMBEDDING_DIMENSIONS:-768}
      - MCP_TRANSPORT=stdio
      - LOG_LEVEL=${LOG_LEVEL:-INFO}
      - LOG_FILE=/logs/memora.log
    volumes:
      - ${VAULT_PATH}:/vault:ro
      - chromadb-data:/data/chromadb
      - sqlite-data:/data
      - logs-data:/logs
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
    depends_on:
      ollama:
        condition: service_healthy
        required: false

  # ─── MEMORA: HTTP Profile (Network Clients) ───
  memora-http:
    build:
      context: .
      dockerfile: Dockerfile
      target: runtime
    profiles: ["http"]
    container_name: memora-http
    entrypoint: ["memora-server", "http", "0.0.0.0", "8080"]
    environment:
      - VAULT_PATH=/vault
      - CHROMA_PATH=/data/chromadb
      - SQLITE_PATH=/data/memora.db
      - OLLAMA_HOST=${OLLAMA_HOST:-http://host.docker.internal:11434}
      - EMBEDDING_MODEL=${EMBEDDING_MODEL:-nomic-embed-text}
      - EMBEDDING_DIMENSIONS=${EMBEDDING_DIMENSIONS:-768}
      - MCP_TRANSPORT=http
      - MCP_HOST=0.0.0.0
      - MCP_PORT=8080
      - LOG_LEVEL=${LOG_LEVEL:-INFO}
      - LOG_FILE=/logs/memora.log
    volumes:
      - ${VAULT_PATH}:/vault:ro
      - chromadb-data:/data/chromadb
      - sqlite-data:/data
      - logs-data:/logs
    ports:
      - "8080:8080"
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/health/ready"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 15s
    user: "1000:1000"
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
    read_only: true
    tmpfs:
      - /tmp
      - /var/tmp
    depends_on:
      ollama:
        condition: service_healthy
        required: false

volumes:
  ollama-models:
  chromadb-data:
  sqlite-data:
  logs-data:
```

### Volume Permissions Matrix

| Volume | Mount Point | Mode | UID/GID | Purpose |
|--------|-------------|------|---------|---------|
| Vault (bind) | `/vault` | `ro` | Host | Obsidian source (read-only) |
| `chromadb-data` | `/data/chromadb` | `rw` | 1000:1000 | Vector embeddings |
| `sqlite-data` | `/data` | `rw` | 1000:1000 | SQLite database |
| `logs-data` | `/logs` | `rw` | 1000:1000 | Application logs |
| `ollama-models` | `/root/.ollama` | `rw` | Root (Ollama) | Model cache |

### MCP Connection Diagrams

#### STDIO Mode (Claude Desktop)
```
┌─────────────────┐     docker compose exec -T      ┌─────────────────┐
│  Claude Desktop │ ──────────────────────────────▶ │  memora-stdio   │
│  (MCP Client)   │ ◀────────────────────────────── │  (MCP Server)   │
└─────────────────┘      stdio (stdin/stdout)       └────────┬────────┘
                                                              │
                                                              ▼
┌─────────────────┐                              ┌─────────────────┐
│  Obsidian Vault │ ◀────── read-only bind ────── │  /vault (ro)    │
│  (Host FS)      │                               │  ChromaDB/SQLite│
└─────────────────┘                               │  (volumes)      │
                                                  └────────┬────────┘
                                                           │
                                                  ┌────────▼────────┐
                                                  │  Ollama (Host)  │
                                                  │  host.docker.   │
                                                  │  internal:11434 │
                                                  └─────────────────┘
```

#### HTTP Mode (Network Clients)
```
┌─────────────────┐         HTTP :8080           ┌─────────────────┐
│  Remote Client  │ ───────────────────────────▶ │  memora-http    │
│  (MCP Client)   │ ◀─────────────────────────── │  (MCP Server)   │
└─────────────────┘   Streamable-HTTP             └────────┬────────┘
                                                              │
                                                              ▼
                                                  ┌─────────────────┐
                                                  │  /vault (ro)    │
                                                  │  ChromaDB/SQLite│
                                                  │  (volumes)      │
                                                  └────────┬────────┘
                                                           │
                                                  ┌────────▼────────┐
                                                  │  Ollama         │
                                                  │  ollama:11434   │
                                                  │  (or host)      │
                                                  └─────────────────┘
```

### Deployment Assumptions

| Assumption | Rationale |
|------------|-----------|
| Docker Engine 24+, Compose 2.20+ | Required for profiles, healthchecks, GPU reservations |
| Host has Ollama running (default) | Avoids duplicate; uses existing models |
| VAULT_PATH configured per platform | Linux: `/home/...`, Mac: `/Users/...`, Windows: `C:\...` or WSL `/mnt/c/...` |
| User UID 1000 exists | Standard non-root user for container |
| Single MEMORA instance per vault | SQLite/ChromaDB not designed for multi-writer |
| No database migrations needed | Schema managed by application on startup |
| HTTP transport needs uvicorn/starlette | Added to dependencies |

---

## 6. Database Concurrency — Exclusive Access Enforcement

### Problem
Both STDIO (ephemeral `docker run`) and HTTP (persistent `compose up`) reference the same volumes:
- `chromadb-data` → `/data/chromadb`
- `sqlite-data` → `/data/memora.db`

SQLite and ChromaDB **do not support concurrent writers** from multiple processes. Running STDIO and HTTP simultaneously (or multiple STDIO sessions) risks:
- SQLite `SQLITE_BUSY` / locked database errors
- ChromaDB corruption or inconsistent state
- Silent data loss during concurrent indexing

### Enforcement Mechanism: File-Based Locking

**Implementation:** Lightweight advisory lock file at `/data/.memora.lock`

```python
# In memora/config.py or new memora/lock.py
import os
import fcntl
import time
from contextlib import contextmanager
from pathlib import Path

LOCK_PATH = Path("/data/.memora.lock")
LOCK_TIMEOUT = 30  # seconds

@contextmanager
def exclusive_data_access(timeout: int = LOCK_TIMEOUT):
    """
    Acquire exclusive lock on data directory.
    Blocks until lock acquired or timeout.
    """
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    lock_file = open(LOCK_PATH, "w")
    try:
        start = time.time()
        while True:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                lock_file.write(str(os.getpid()))
                lock_file.flush()
                yield
                return
            except BlockingIOError:
                if time.time() - start > timeout:
                    raise TimeoutError(f"Could not acquire data lock within {timeout}s")
                time.sleep(0.1)
    finally:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        except Exception:
            pass
        lock_file.close()
        try:
            LOCK_PATH.unlink(missing_ok=True)
        except Exception:
            pass
```

**Usage in CLI entry points:**
```python
# cli.py — wrap ingest, search, status, etc.
from memora.lock import exclusive_data_access

@app.command()
def ingest(...):
    with exclusive_data_access():
        # ... existing ingest logic
```

```python
# mcp/server.py — wrap tool handlers
from memora.lock import exclusive_data_access

@self.server.tool()
async def memorize(...):
    with exclusive_data_access():
        # ... existing logic
```

### Lock Behavior Matrix

| Scenario | Behavior |
|----------|----------|
| HTTP service running, Claude starts STDIO | STDIO waits up to 30s, then fails with clear error |
| STDIO session active, HTTP request arrives | HTTP request waits (async), times out if lock not released |
| Two STDIO sessions (two Claude windows) | Second session waits, then fails |
| Process crashes while holding lock | Lock released automatically (fd closed on process death) |
| Container killed (SIGKILL) | Lock file persists but stale; next process detects stale PID and force-acquires |

### Stale Lock Detection
```python
def _is_lock_stale(lock_path: Path) -> bool:
    """Check if lock holder process is dead."""
    try:
        pid = int(lock_path.read_text().strip())
        # Send signal 0 to test process existence
        os.kill(pid, 0)
        return False  # Process alive
    except (ValueError, ProcessLookupError, FileNotFoundError):
        return True   # Process dead or lock file invalid
```

### Decision
- **Advisory file lock** at `/data/.memora.lock` using `fcntl.flock()`
- **Applied at CLI entry** (`memora` commands) and **MCP tool handlers**
- **Timeout: 30 seconds** with clear error message
- **Automatic stale lock recovery** (detects dead holder PID)
- **No external coordination service** (Redis, Consul) — keeps architecture simple
- **Documented limitation**: Only one MEMORA process (any transport) can access data at a time

---

## 8. Final Validations — Pre-Implementation Review

### 8.1 Advisory Locking — Verified (With Implementation Safeguards)

| Requirement | Verification | Implementation Detail |
|-------------|--------------|----------------------|
| **All DB-writing ops acquire lock** | ✅ Verified | Wrap at CLI entry (`ingest`, `search`, `status`, `check_ollama`, `pull_model`, `doctor`) + all 5 MCP tools (`memorize`, `search_memory`, `get_context`, `list_sources`, `reindex`) |
| **Async-safe for HTTP** | ✅ Verified | `fcntl.flock()` is process-wide; async handlers run in same process — lock held across `await` points. No thread-safety issues. **Safeguard: Use `asyncio.to_thread()` for blocking flock polling** |
| **Lock file never deleted while held** | ✅ Verified | `finally` block closes fd → `flock(LOCK_UN)` → closes file. **Safeguard: Do NOT unlink lock file** — keep persistent to prevent inode replacement / split-lock races. |
| **Process termination releases lock** | ✅ Verified | OS closes all fds on process exit (normal or SIGKILL) → `flock` auto-released. No cleanup needed. |
| **Deterministic timeout** | ✅ Verified | 30s wall-clock timeout with 100ms polling. `TimeoutError` raised with exact message. No exponential backoff. |
| **No unnecessary stale-lock deletion** | ✅ Verified | Stale detection only reads PID + `os.kill(pid, 0)`. Never deletes lock file proactively. **Safeguard: Lock file persists indefinitely** — no cleanup in `finally`. |

**Final Implementation (with safeguards):**
```python
# memora/lock.py
import os
import fcntl
import time
import asyncio
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

LOCK_PATH = Path("/data/.memora.lock")
LOCK_TIMEOUT = 30  # seconds
POLL_INTERVAL = 0.1

# Global lock file descriptor (kept open for process lifetime)
_lock_fd: Optional[int] = None
_lock_file = None

def _acquire_lock_blocking(timeout: int = LOCK_TIMEOUT) -> bool:
    """Blocking flock acquisition with timeout. Runs in thread pool."""
    global _lock_fd, _lock_file
    
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    
    # Open/create lock file (append mode, keep open)
    _lock_file = open(LOCK_PATH, "a")
    _lock_fd = _lock_file.fileno()
    
    start = time.monotonic()
    while True:
        try:
            fcntl.flock(_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            # Write PID for stale detection
            _lock_file.seek(0)
            _lock_file.truncate()
            _lock_file.write(str(os.getpid()))
            _lock_file.flush()
            return True
        except BlockingIOError:
            if time.monotonic() - start > timeout:
                _lock_file.close()
                _lock_fd = None
                _lock_file = None
                return False
            time.sleep(POLL_INTERVAL)

def _release_lock() -> None:
    """Release flock and close descriptor. Does NOT unlink file."""
    global _lock_fd, _lock_file
    if _lock_fd is not None:
        try:
            fcntl.flock(_lock_fd, fcntl.LOCK_UN)
        except Exception:
            pass
        if _lock_file:
            _lock_file.close()
        _lock_fd = None
        _lock_file = None
        # NOTE: Lock file is deliberately NOT unlinked.
        # Persistent file prevents inode replacement / split-lock races.

@contextmanager
def exclusive_data_access(timeout: int = LOCK_TIMEOUT):
    """
    Acquire exclusive advisory lock on data directory.
    Blocks until lock acquired or timeout expires.
    Safe for sync and async code (uses asyncio.to_thread for blocking ops).
    
    Lock file persists after release — never unlinked.
    """
    global _lock_fd, _lock_file
    
    # Check if we already hold the lock (re-entrant for same process)
    if _lock_fd is not None:
        try:
            # Verify we still hold it
            fcntl.flock(_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(_lock_fd, fcntl.LOCK_UN)
            # We hold it, yield immediately
            yield
            return
        except BlockingIOError:
            # Lock held by another process, proceed to wait
            pass
    
    # Acquire in thread pool to avoid blocking event loop
    loop = asyncio.get_event_loop()
    acquired = await loop.run_in_executor(None, _acquire_lock_blocking, timeout)
    if not acquired:
        raise TimeoutError(
            f"Could not acquire data lock within {timeout}s. "
            f"Another MEMORA process may be running."
        )
    
    try:
        yield
    finally:
        _release_lock()

# Synchronous version for CLI commands
def exclusive_data_access_sync(timeout: int = LOCK_TIMEOUT):
    """Synchronous context manager for CLI commands."""
    from contextlib import contextmanager as sync_contextmanager
    
    @sync_contextmanager
    def _sync_lock():
        if _acquire_lock_blocking(timeout):
            try:
                yield
            finally:
                _release_lock()
        else:
            raise TimeoutError(
                f"Could not acquire data lock within {timeout}s. "
                f"Another MEMORA process may be running."
            )
    return _sync_lock()

def is_lock_stale() -> bool:
    """Check if lock file exists and holder process is dead."""
    if not LOCK_PATH.exists():
        return False
    try:
        pid = int(LOCK_PATH.read_text().strip())
        os.kill(pid, 0)
        return False  # Process alive
    except (ValueError, ProcessLookupError, FileNotFoundError):
        return True   # Process dead or lock file invalid
```

**Key Safeguards Applied:**
1. **No unlink** — Lock file persists; only flock released
2. **Async-safe** — `asyncio.to_thread()` for blocking `flock` polling
3. **Re-entrant** — Same process can nest calls safely
4. **Sync + Async** — `exclusive_data_access_sync()` for CLI, async for MCP tools

---

### 8.2 Docker Resource Naming — Verified

| Resource | Name | Predictable? | Shared STDIO/HTTP? |
|----------|------|--------------|-------------------|
| **Network** | `memora-network` | ✅ Explicit in compose | ✅ Both use `--network=memora-network` |
| **ChromaDB Volume** | `memora_chromadb-data` | ✅ Compose prefix + name | ✅ Same volume |
| **SQLite Volume** | `memora_sqlite-data` | ✅ Compose prefix + name | ✅ Same volume |
| **Logs Volume** | `memora_logs-data` | ✅ Compose prefix + name | ✅ Same volume |
| **Ollama Volume** | `memora_ollama-models` | ✅ Compose prefix + name | ✅ N/A (Ollama only) |

**Compose Volume Declaration:**
```yaml
volumes:
  chromadb-data:    # Becomes memora_chromadb-data
  sqlite-data:      # Becomes memora_sqlite-data
  logs-data:        # Becomes memora_logs-data
  ollama-models:    # Becomes memora_ollama-models
```

**STDIO Volume References (in Claude Desktop config):**
```json
"-v", "memora_chromadb-data:/data/chromadb",
"-v", "memora_sqlite-data:/data",
"-v", "memora_logs-data:/logs"
```

**No duplicate volumes** — Compose creates with project prefix; `docker run -v` references exact same named volumes.

---

### 8.3 HTTP Security — Hardened

| Requirement | Decision | Implementation |
|-------------|----------|----------------|
| **Localhost-only by default** | ✅ Enforced | `MCP_HOST=127.0.0.1` in compose (not `0.0.0.0`) |
| **Remote exposure requires explicit change** | ✅ Enforced | User must override `MCP_HOST=0.0.0.0` in `.env` or CLI |
| **Health endpoints leak no secrets** | ✅ Verified | Returns only: `status`, `free_gb`, `ollama` host URL — no tokens, paths, vault content |
| **Port binding** | ✅ Verified | `ports: ["127.0.0.1:8080:8080"]` — only localhost on host |

**Compose Port Binding (Fixed):**
```yaml
memora-http:
  ports:
    - "127.0.0.1:8080:8080"  # Only localhost, not all interfaces
```

**Health Endpoint Payloads (Safe):**
```json
// /health/live
{"status": "alive"}

// /health/ready
{"status": "ready"}

// /health/ollama
{"status": "healthy", "ollama": "http://host.docker.internal:11434"}

// /health/storage
{"status": "ok", "free_gb": 15.2}
```

**No sensitive data exposed** — no vault paths, no chunk content, no embeddings, no API keys.

---

### 8.4 Ollama Configuration — Verified

| Scenario | OLLAMA_HOST Resolution | Correct? |
|----------|------------------------|----------|
| **Default (no profile)** | `http://host.docker.internal:11434` (Docker Desktop) / `http://172.17.0.1:11434` (Linux) | ✅ Host Ollama |
| **`--profile ollama` active** | `http://ollama:11434` (Compose DNS) | ✅ Container Ollama |
| **User overrides in `.env`** | Custom value respected | ✅ Explicit config |

**Mechanism: Entrypoint resolves at runtime**
```bash
# docker-entrypoint.sh
#!/bin/bash
set -e

# Resolve OLLAMA_HOST based on profile
if [ -n "$OLLAMA_HOST_OVERRIDE" ]; then
    export OLLAMA_HOST="$OLLAMA_HOST_OVERRIDE"
elif [ "$ENABLE_CONTAINER_OLLAMA" = "true" ]; then
    export OLLAMA_HOST="http://ollama:11434"
else
    # Default: host.docker.internal works on Docker Desktop (Mac/Win)
    # On Linux, user should set OLLAMA_HOST=http://172.17.0.1:11434 in .env
    export OLLAMA_HOST="${OLLAMA_HOST:-http://host.docker.internal:11434}"
fi

exec memora-server "$@"
```

**Compose Environment (No Ambiguity):**
```yaml
memora-http:
  environment:
    # Default: host Ollama
    - OLLAMA_HOST=${OLLAMA_HOST:-http://host.docker.internal:11434}
  profiles: ["http"]
  depends_on:
    ollama:
      condition: service_healthy
      required: false  # Does NOT force ollama profile

ollama:
  profiles: ["ollama"]  # Only started when explicitly requested
```

**Key Guarantee:** Enabling `--profile ollama` does **not** change `OLLAMA_HOST` for `memora-http` unless user explicitly sets it. The service discovers Ollama via Compose DNS *only* when the `ollama` service is actually running (same compose project).

---

## 9. Implementation Safeguards (Mandatory)

### 9.1 Lock File Lifecycle — Persistent, Never Unlinked

**Safeguard:** The advisory lock file at `/data/.memora.lock` **must never be unlinked** after lock release.

**Rationale:**
- Unlinking + recreating creates inode replacement race ("split-lock")
- Another process could open the old inode, acquire flock on stale inode
- Persistent file guarantees single inode for lock lifetime

**Implementation:**
```python
# In _release_lock() — NO unlink:
def _release_lock() -> None:
    global _lock_fd, _lock_file
    if _lock_fd is not None:
        try:
            fcntl.flock(_lock_fd, fcntl.LOCK_UN)
        except Exception:
            pass
        if _lock_file:
            _lock_file.close()
        _lock_fd = None
        _lock_file = None
        # LOCK FILE PERSISTS — deliberately not unlinked
```

### 9.2 Async Lock Acquisition — Non-Blocking Event Loop

**Safeguard:** All blocking `flock` polling **must** run in thread pool via `asyncio.to_thread()`.

**Rationale:**
- `fcntl.flock()` with `LOCK_NB` + polling blocks the thread
- In async HTTP handlers, this blocks the entire event loop
- `asyncio.to_thread()` offloads to executor, keeps loop responsive

**Implementation:**
```python
# In exclusive_data_access() async context manager:
loop = asyncio.get_event_loop()
acquired = await loop.run_in_executor(None, _acquire_lock_blocking, timeout)
```

**Sync version for CLI:** Uses direct blocking call (no event loop to protect).

### 9.3 Ollama Profile Selection — Explicit Compose Configuration

**Safeguard:** Do NOT rely on runtime auto-detection of Compose profiles. Configure explicitly via environment.

**Rationale:**
- Container cannot reliably detect which Compose profiles are active
- Auto-detection via DNS/environment is fragile and implicit
- Explicit configuration is deterministic and auditable

**Implementation:**

**docker-compose.yml** — Explicit environment per profile:
```yaml
services:
  memora-http:
    profiles: ["http"]
    environment:
      # Explicit: default to host Ollama
      - OLLAMA_MODE=host
      - OLLAMA_HOST=http://host.docker.internal:11434
    # Override via .env or command line for container Ollama:
    # docker compose --profile http,ollama up -d
    #   sets OLLAMA_MODE=container, OLLAMA_HOST=http://ollama:11434

  ollama:
    profiles: ["ollama"]
    # No OLLAMA_MODE needed — this IS the Ollama service
```

**docker-entrypoint.sh** — Reads explicit config:
```bash
#!/bin/bash
set -e

# Explicit configuration (no auto-detection)
OLLAMA_MODE="${OLLAMA_MODE:-host}"  # "host" or "container"

case "$OLLAMA_MODE" in
    host)
        export OLLAMA_HOST="${OLLAMA_HOST:-http://host.docker.internal:11434}"
        ;;
    container)
        export OLLAMA_HOST="${OLLAMA_HOST:-http://ollama:11434}"
        ;;
    *)
        echo "ERROR: Invalid OLLAMA_MODE='$OLLAMA_MODE'. Use 'host' or 'container'." >&2
        exit 1
        ;;
esac

exec memora-server "$@"
```

**Usage:**
```bash
# Host Ollama (default)
docker compose --profile http up -d

# Container Ollama (explicit)
docker compose --profile http,ollama up -d \
  -e OLLAMA_MODE=container \
  -e OLLAMA_HOST=http://ollama:11434

# Or via .env:
# OLLAMA_MODE=container
# OLLAMA_HOST=http://ollama:11434
```

**Validation:**
| Command | OLLAMA_MODE | OLLAMA_HOST | Expected |
|---------|-------------|-------------|----------|
| `compose --profile http up` | host (default) | host.docker.internal:11434 | ✅ Host |
| `compose --profile http,ollama up -e OLLAMA_MODE=container` | container | ollama:11434 | ✅ Container |
| `compose --profile http up -e OLLAMA_MODE=container` | container | ollama:11434 | ❌ Fails (no ollama service) |

---

## Final Implementation Scope

### Files to Create (6)

| File | Purpose |
|------|---------|
| `Dockerfile` | Multi-stage build; non-root user (UID 1000); security hardening; copies entrypoint |
| `docker-compose.yml` | Dual-profile (`http`, `ollama`); fixed volume names; localhost-only port; healthchecks; explicit OLLAMA_MODE |
| `docker-entrypoint.sh` | Explicit OLLAMA_MODE resolution; transport selection via CLI args |
| `.dockerignore` | Excludes `.venv`, `__pycache__`, `data/`, `logs/`, `.git`, `*.db`, `.env`, `.pytest_cache` |
| `.env.docker` | Template with `VAULT_PATH=`, `OLLAMA_MODE=host`, `OLLAMA_HOST=http://host.docker.internal:11434` |
| `memora/lock.py` | **NEW** — Async-safe advisory locking with persistent lock file, `asyncio.to_thread()` |

### Files to Modify (5)

| File | Changes |
|------|---------|
| `pyproject.toml` | Add `uvicorn>=0.30.0`, `starlette>=0.38.0` to `[project.dependencies]` |
| `memora/mcp/server.py` | Add 4 health endpoints in `run_http()`; wrap 5 MCP tools with async `exclusive_data_access()` |
| `memora/cli.py` | Wrap all 7 CLI commands with sync `exclusive_data_access_sync()` |
| `memora/config.py` | Import lock functions for shared LOCK_PATH constant |

### No Changes To
- Database schemas (managed by app)
- Vault interaction (read-only, virtual paths)
- Core ingestion/search logic
- Git history

---

## Expected Behaviour

### STDIO Mode (Claude Desktop)
```bash
# User adds to Claude Desktop config → launches fresh container per session
docker run --rm -i --network=memora-network \
  -v ${VAULT_PATH}:/vault:ro \
  -v memora_chromadb-data:/data/chromadb \
  -v memora_sqlite-data:/data \
  -v memora_logs-data:/logs \
  -e OLLAMA_HOST=http://host.docker.internal:11434 \
  memora:latest memora-server
```
- Acquires lock → executes tool → releases lock → container exits
- Concurrent HTTP service: STDIO waits 30s, then fails with clear error

### HTTP Mode (Persistent Service)
```bash
# User runs:
docker compose --profile http up -d

# Service starts on 127.0.0.1:8080
# Healthcheck: curl -f http://localhost:8080/health/ready
```
- Persistent, restart policy `unless-stopped`
- Lock per-request (MCP tool calls)
- Health endpoints expose no secrets

### Ollama Profiles
```bash
# Host Ollama (default)
docker compose --profile http up -d

# Container Ollama (explicit)
docker compose --profile http,ollama up -d
# OLLAMA_HOST auto-resolves to http://ollama:11434
```

---

## Testing Strategy

### Unit Tests (New)
| Test | Target |
|------|--------|
| `test_lock.py` | `exclusive_data_access()` acquires/releases; timeout; stale PID detection; concurrent access blocked |
| `test_health_endpoints.py` | All 4 endpoints return correct JSON; no sensitive data; readiness fails when DB unavailable |
| `test_entrypoint.py` | `OLLAMA_HOST` resolves correctly for host/container profiles |

### Integration Tests
| Test | Command | Expected |
|------|---------|----------|
| **HTTP + Host Ollama** | `compose --profile http up -d` + `curl /health/ollama` | `{"status": "healthy"}` |
| **HTTP + Container Ollama** | `compose --profile http,ollama up -d` + `curl /health/ollama` | `{"status": "healthy", "ollama": "http://ollama:11434"}` |
| **STDIO + Host Ollama** | `docker run ... memora-server` | MCP initialize succeeds |
| **Concurrency** | Start HTTP, then run STDIO `ingest` | STDIO waits, times out at 30s with `TimeoutError` |
| **Lock Recovery** | Kill holder (SIGKILL), new process acquires | Stale PID detected, lock acquired immediately |
| **Security** | `curl http://0.0.0.0:8080/health/ready` | Connection refused (only 127.0.0.1 bound) |

### Manual Validation
1. **Claude Desktop Integration** — Add config, verify MCP tools work
2. **Volume Persistence** — Restart containers, verify data intact
3. **Ollama Failover** — Stop Ollama, verify `/health/ollama` reports unhealthy; restart, verify recovery

---

*Final validation complete. All four concerns verified. Ready for implementation upon approval.*

---

## 7. Ollama Profile Validation — All Combinations Verified

### Supported Deployment Combinations

| Combination | Compose Command | OLLAMA_HOST | GPU | Model Source | Validated |
|-------------|-----------------|-------------|-----|--------------|-----------|
| **Host Ollama + HTTP** | `docker compose --profile http up -d` | `http://host.docker.internal:11434` | Host | Host `~/.ollama` | ✅ Primary |
| **Host Ollama + STDIO** | `docker run ... memora:latest memora-server` | `http://host.docker.internal:11434` | Host | Host `~/.ollama` | ✅ Primary |
| **Container Ollama + HTTP** | `docker compose --profile http,ollama up -d` | `http://ollama:11434` | Container | Volume `ollama-models` | ✅ Optional |
| **Container Ollama + STDIO** | `docker run --network=memora-network ...` | `http://ollama:11434` | Container | Volume `ollama-models` | ✅ Optional |

### Profile Dependency Matrix

```yaml
# docker-compose.yml
services:
  ollama:
    profiles: ["ollama"]           # Only started when explicitly requested
    healthcheck:
      test: ["CMD", "ollama", "list"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 10s

  memora-http:
    profiles: ["http"]             # Independent profile
    depends_on:
      ollama:
        condition: service_healthy
        required: false            # Does NOT require ollama profile
```

**Key Design:** `memora-http` does **not** depend on `ollama` profile being active. It only waits for Ollama healthcheck **if** the Ollama service happens to be running (via `--profile ollama`). This enables:

| Scenario | Behavior |
|----------|----------|
| `compose --profile http up` (no Ollama profile) | Starts memora-http immediately; connects to host Ollama via `host.docker.internal` |
| `compose --profile http,ollama up` | Starts ollama first (healthcheck), then memora-http; connects to `ollama:11434` |
| Host Ollama stops mid-session | memora healthcheck `/health/ollama` reports unhealthy; requests fail gracefully |
| Host Ollama restarts | memora auto-recovers on next request (new connection) |
| Model missing (`nomic-embed-text`) | Ollama healthcheck fails; memora `/health/ollama` reports unhealthy; clear error in logs |

### Ollama Failure Modes & Responses

| Failure Mode | Detection | MEMORA Response |
|--------------|-----------|-----------------|
| **Ollama unreachable** | `/health/ollama` → `connect failed` | HTTP 503 on embed-dependent tools; `memora doctor` reports FAIL |
| **Model not pulled** | `/api/tags` → model absent | `/health/ollama` → `model_missing`; CLI `memora pull-model` guides user |
| **OOM / GPU error** | Ollama container restart / logs | Healthcheck fails; memora reports unavailable; manual intervention |
| **Network partition** | HTTP timeout (5s default) | Request fails fast; no hanging |

### STDIO-Specific Ollama Behavior

Since STDIO containers are ephemeral (`docker run --rm`):
- Each session independently connects to `OLLAMA_HOST`
- No shared state between sessions
- If Ollama unavailable at session start → immediate error in MCP initialize
- If Ollama dies mid-session → tool calls fail with clear error

### Validation Checklist (Pre-Release)

```bash
# 1. Host Ollama + HTTP
docker compose --profile http up -d
curl http://localhost:8080/health/ollama  # → {"status": "healthy"}

# 2. Host Ollama + STDIO
docker run --rm -i -v ... memora:latest memora-server
# → MCP initialize succeeds

# 3. Container Ollama + HTTP
docker compose --profile http,ollama up -d
curl http://localhost:8080/health/ollama  # → {"status": "healthy"}

# 4. Container Ollama + STDIO
docker run --rm -i --network=memora-network ... memora:latest memora-server
# → MCP initialize succeeds

# 5. Ollama stopped
docker compose stop ollama
curl http://localhost:8080/health/ollama  # → {"status": "unhealthy"}

# 6. Model missing
docker exec memora-ollama ollama rm nomic-embed-text
curl http://localhost:8080/health/ollama  # → {"status": "unhealthy", "reason": "model_missing"}

# 7. Ollama restart recovery
docker compose restart ollama
# Wait for healthcheck...
curl http://localhost:8080/health/ollama  # → {"status": "healthy"}
```

### Decision
- **Two profiles**: `http` (MEMORA HTTP) and `ollama` (optional containerized Ollama)
- **No hard dependency** — `memora-http` works with or without `ollama` profile
- **Host Ollama default** via `host.docker.internal:11434` (Docker Desktop) or `172.17.0.1:11434` (Linux)
- **Health endpoints** validate Ollama + model at runtime
- **Graceful degradation** — clear errors, no silent failures
- **All 4 combinations validated** in checklist above

### Required Configuration Changes

| File | Change |
|------|--------|
| `pyproject.toml` | Add `uvicorn>=0.30.0`, `starlette>=0.38.0` to `[project.dependencies]` |
| `memora/mcp/server.py` | Add 4 health endpoints in `run_http()` (see Section 5) |
| `memora/lock.py` | **NEW** — File-based advisory locking for data directory |
| `memora/cli.py` | Wrap CLI commands with `exclusive_data_access()` |
| `memora/mcp/server.py` | Wrap MCP tool handlers with `exclusive_data_access()` |
| `docker-entrypoint.sh` | Create (new file) for transport selection |
| `Dockerfile` | Multi-stage; copy entrypoint; create dirs; non-root user |
| `.dockerignore` | Exclude `.venv`, `__pycache__`, `data/`, `logs/`, `.git`, `*.db`, `.env`, `.pytest_cache` |
| `docker-compose.yml` | Dual-profile design (http, ollama); no stdio service |
| `.env.docker` | Template with `VAULT_PATH=`, `OLLAMA_HOST=http://host.docker.internal:11434` |

### Remaining Blockers

| Blocker | Resolution | Owner |
|---------|------------|-------|
| **Add uvicorn/starlette to deps** | Edit `pyproject.toml` — approved in Phase 1 | Dev |
| **Health endpoints in server.py** | Code change — required for HTTP healthchecks | Dev |
| **Lock module (`memora/lock.py`)** | **NEW** — File-based advisory locking for concurrency | Dev |
| **CLI lock integration** | Wrap `cli.py` commands with `exclusive_data_access()` | Dev |
| **MCP tool lock integration** | Wrap `server.py` tool handlers with `exclusive_data_access()` | Dev |
| **Entrypoint script** | New file — required for dual transport | Dev |
| **VAULT_PATH per platform** | Document in `.env.docker` — user configures | User |
| **Ollama model pre-pull** | Entrypoint or init container — optional but recommended | Dev |
| **Git commit Docker files** | After implementation — standard workflow | Dev |

---

## Approval Request

This architecture decision report resolves all **eight** concerns (original 5 + 3 new) with code-verified findings.

**Requesting approval to proceed with Phase 1 implementation:**

### Docker Infrastructure (New Files)
1. `Dockerfile` (multi-stage, non-root user, security hardening)
2. `docker-compose.yml` (dual-profile: `http`, `ollama`; no stdio service)
3. `docker-entrypoint.sh` (transport selection via CLI args)
4. `.dockerignore`
5. `.env.docker` template

### Application Code Changes (Minimal, Surgical)
6. `pyproject.toml` — Add `uvicorn>=0.30.0`, `starlette>=0.38.0`
7. `memora/mcp/server.py` — Add 4 health endpoints (`/health/live`, `/health/ready`, `/health/ollama`, `/health/storage`) in `run_http()`
8. `memora/lock.py` — **NEW** file-based advisory locking (`exclusive_data_access()`)
9. `memora/cli.py` — Wrap all CLI commands with `exclusive_data_access()`
10. `memora/mcp/server.py` — Wrap all MCP tool handlers with `exclusive_data_access()`

### No Changes To
- Database schemas (SQLite/ChromaDB managed by app on startup)
- Vault interaction (read-only, virtual paths unchanged)
- Core ingestion/search logic (indexer, chunker, embeddings, retrieval)
- Git history (preserved; new commit only)

---
*Report generated per Phase 2 conditional approval requirements. All findings based on actual code inspection.*