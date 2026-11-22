# MEMORA Lifecycle Management

## Overview

The MEMORA Lifecycle Manager provides a unified CLI for managing the complete MEMORA deployment through simple commands. It eliminates manual startup procedures by automatically validating system requirements, configuration, dependencies, storage, networking, and Docker availability before starting MEMORA.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    memora --start                             │
├─────────────────────────────────────────────────────────────┤
│  1. Resolve Project Root (MEMORA_HOME / CWD / Package)       │
│  2. Load Configuration (.env / .env.docker)                  │
│  3. Preflight Validation Engine                              │
│     ├── System Requirements (OS, Python, Docker)             │
│     ├── Configuration (compose, env, vault)                  │
│     ├── Ollama (Host/Container mode)                         │
│     ├── Networking (ports, conflicts)                        │
│     └── Storage (dirs, permissions, volumes)                 │
│  4. Display Validation Results                               │
│  5. Determine Compose Profiles (http / ollama)               │
│  6. Validate Compose Configuration                           │
│  7. Build Image (if needed)                                  │
│  8. Start Services (docker compose up)                       │
│  9. Wait for Health Checks                                   │
│ 10. Verify HTTP Health Endpoints                             │
│ 11. Verify Ollama Connectivity                               │
│ 12. Display Startup Report                                   │
└─────────────────────────────────────────────────────────────┘
```

## Commands

### Primary Lifecycle Commands

| Command | Description | Options |
|---------|-------------|---------|
| `memora --start` | Full startup with validation | `--skip-preflight`, `--no-build` |
| `memora --stop` | Graceful shutdown | `-v/--remove-volumes` (DANGEROUS) |
| `memora --restart` | Restart with health check | — |
| `memora --status` | Comprehensive status report | — |
| `memora --doctor` | System diagnostics | `--json`, `--verbose` |
| `memora --logs` | Service logs | `-f/--follow`, `-n/--tail` |
| `memora --version` | Version info | — |

### Subcommand Equivalents

All commands are also available as subcommands:
```bash
memora lifecycle start
memora lifecycle stop
memora lifecycle restart
memora lifecycle status
memora lifecycle doctor
memora lifecycle logs
memora lifecycle version
```

## Preflight Validation Engine

### A. System Requirements
- **OS Compatibility**: Linux, macOS, Windows (WSL2)
- **Python Version**: ≥ 3.10 (warns on 3.9, fails on <3.9)
- **Docker CLI**: Available in PATH
- **Docker Daemon**: Responsive (`docker info`)
- **Docker Compose**: v2 plugin or v1 standalone
- **Permissions**: Docker group membership (Linux), admin not required (Windows)

### B. Configuration Validation
- `docker-compose.yml` exists and valid
- `Dockerfile` exists
- `.env.docker` template exists
- `.env` user config exists (warn if missing)
- Required env vars: `VAULT_PATH`
- `OLLAMA_MODE` ∈ {`host`, `container`}
- Vault path exists and contains `.obsidian/`
- Named volumes defined: `chromadb-data`, `sqlite-data`, `logs-data`, `ollama-models`
- Compose config resolves: `docker compose config`

### C. Ollama Validation

#### Host Mode (`OLLAMA_MODE=host`)
- Ollama binary in PATH
- API responding at `OLLAMA_HOST` (default: `http://host.docker.internal:11434`)
- Embedding model (`EMBEDDING_MODEL`, default: `nomic-embed-text`) available
- Provides controlled start mechanism if installed but not running

#### Container Mode (`OLLAMA_MODE=container`)
- Ollama service defined in compose
- `--profile ollama` enabled
- Container health check passing
- Model available inside container

### D. Networking Validation
- MCP HTTP port (`MCP_PORT`, default: 8080) availability
- Identifies process/container holding port
- **Smart detection**: If port 8080 occupied by healthy `memora-http` container, reports as OK (not conflict)

### E. Storage Validation
- SQLite directory writable
- ChromaDB directory writable
- Logs directory writable
- Volume mount configuration valid
- Vault accessibility (read-only mount respected)
- Never modifies user vault content

## Startup Orchestration

### Sequence
1. **Resolve Project Root**: `MEMORA_HOME` → CWD (pyproject.toml/.env) → package location
2. **Load Config**: Pydantic Settings from `.env` (or `.env.docker` for Docker)
3. **Preflight Validation**: All checks above
4. **Display Results**: Color-coded table with ERROR/WARN/INFO
5. **Fail Fast**: Stop on ERROR, continue on WARN
6. **Determine Profiles**: `http` always; `ollama` if `OLLAMA_MODE=container`
7. **Validate Compose**: `docker compose --profile X,Y config`
8. **Build Image**: `docker compose --profile X,Y build`
9. **Start Services**: `docker compose --profile X,Y up -d`
10. **Wait Health**: Poll container health (timeout: 120s, interval: 5s)
11. **Verify Endpoints**: HTTP GET `/health/live`, `/health/ready`, `/health/ollama`, `/health/storage`
12. **Verify Ollama**: API call to configured host
13. **Startup Report**: Endpoint URLs, transport, mode, vault path

### Idempotency
- Running `memora --start` twice: No duplicate containers, no corruption
- Uses fixed container names: `memora-http`, `memora-ollama`
- `docker compose up -d` is inherently idempotent

## Stop and Restart

### `memora --stop`
- Graceful `docker compose down` (no `-v`)
- Preserves all named volumes
- Does not stop unrelated containers
- Does not terminate independent host Ollama

### `memora --stop -v` (DANGEROUS)
- Requires explicit confirmation
- Removes all persistent data (ChromaDB, SQLite, logs, Ollama models)

### `memora --restart`
- Runs appropriate preflight checks
- `docker compose restart`
- Waits for health checks
- Verifies health endpoints

## Status and Diagnostics

### `memora --status` Reports
| Component | Details |
|-----------|---------|
| Docker Daemon | Running / Not accessible / Error |
| Containers | Name, Status, Health, Ports, Image |
| MCP HTTP | Available/Not available, endpoint URL, readiness |
| Ollama | Connected/Not accessible, host, model availability |
| Storage | ChromaDB path, SQLite path, Logs path |
| Vault | Path, Valid (has .obsidian/) |
| Transport | stdio / http |
| Endpoint | Full URL |

### `memora --doctor` Checks
- Python Environment (version, executable)
- Dependencies (all required packages)
- Configuration (vault, paths, embedding dims)
- Ollama Connectivity (host + model)
- Embedding Model (pulled + dimensions match)
- ChromaDB (accessible + metadata consistency)
- SQLite (integrity + WAL mode)
- Obsidian Vault (.obsidian + .md count + permissions)
- Embedding Pipeline (end-to-end test)
- MCP Configuration (version + transport)
- Storage (dirs + permissions + disk space)

## Host vs Container Ollama Modes

| Aspect | Host Mode (`OLLAMA_MODE=host`) | Container Mode (`OLLAMA_MODE=container`) |
|--------|-------------------------------|------------------------------------------|
| **Endpoint** | `http://host.docker.internal:11434` | `http://ollama:11434` (Compose DNS) |
| **Fallback** | Container Ollama | Host Ollama |
| **Profiles** | `http` | `http,ollama` |
| **Startup** | Validates host Ollama running | Starts ollama container via compose |
| **Model Check** | Against host Ollama API | Against container Ollama API |
| **GPU** | Host GPU via Docker Desktop | `deploy.resources.reservations.devices` in compose |

**Do Not**: Silently switch modes, auto-download models, or assume availability.

## Networking

### Default Binding
- HTTP endpoint: `127.0.0.1:8080` (localhost only)
- Never exposes beyond intended binding
- No automatic firewall modifications

### Port Conflict Resolution
| Scenario | Action |
|----------|--------|
| Port free | ✅ OK |
| Port held by healthy `memora-http` | ✅ OK (idempotent) |
| Port held by unhealthy `memora-http` | ⚠️ WARN (restart recommended) |
| Port held by other process | ❌ ERROR (identify PID/container) |

## Security & Reliability

| Requirement | Implementation |
|-------------|----------------|
| No secrets in logs | Config logged without sensitive values |
| No volume deletion | `docker compose down` (no `-v`) |
| No config overwrite | User `.env` never modified |
| No vault modification | Read-only mount (`:ro`) |
| No duplicate Ollama | Host mode checks existing process |
| Graceful shutdown | SIGTERM handling in entrypoint |
| Meaningful exit codes | 0=success, 1=error, 2=warn |
| No destructive cleanup | Explicit confirmation for `-v` |

## Windows Installation

### Installer Scripts
| Script | Usage |
|--------|-------|
| `install.ps1` | PowerShell (recommended, admin for PATH) |
| `install.bat` | CMD (admin for PATH) |

### Installation Steps
```powershell
# 1. Clone/download MEMORA
# 2. Run installer (as Administrator for PATH)
.\install.ps1

# 3. Restart terminal
# 4. Configure vault
copy $env:LOCALAPPDATA\MEMORA\.env.example $env:LOCALAPPDATA\MEMORA\.env
notepad $env:LOCALAPPDATA\MEMORA\.env  # Edit VAULT_PATH

# 5. Start
memora --start
```

### How It Works
1. Installs to `%LOCALAPPDATA%\MEMORA`
2. Creates `.venv` virtual environment
3. `pip install -e .` (editable install)
4. Creates `scripts/memora.bat` and `scripts/memora.ps1`
5. Adds scripts dir to user PATH
6. Verifies with `memora --version`

### Project Root Discovery
Priority order:
1. `MEMORA_HOME` env var (explicit override)
2. Current working directory (has `pyproject.toml` or `.env`)
3. Package installation location (fallback)

## Configuration Files

| File | Purpose |
|------|---------|
| `.env` | User configuration (gitignored) |
| `.env.example` | Template for local development |
| `.env.docker` | Template for Docker deployment |
| `docker-compose.yml` | Service definitions (profiles: `http`, `ollama`) |
| `Dockerfile` | Multi-stage build (builder → runtime) |
| `docker-entrypoint.sh` | Resolves `OLLAMA_MODE`, delegates to `memora-server` |

## Health Endpoints

| Endpoint | Purpose | Response |
|----------|---------|----------|
| `/health/live` | Liveness probe | `{"status": "alive"}` |
| `/health/ready` | Readiness probe | `{"status": "ready", "checks": {...}}` |
| `/health/ollama` | Ollama connectivity | `{"status": "healthy", "model_available": true}` |
| `/health/storage` | SQLite + ChromaDB | `{"status": "healthy", "components": {...}}` |

## Testing

### Unit Tests (No Docker Required)
```bash
pytest tests/test_lifecycle_cli.py -v
# 22 tests: project root, config, preflight, compose, orchestration, validation, CLI parsing
```

### Full Test Suite
```bash
pytest tests/ -v
# 193 tests including lifecycle
```

### Mock Strategy
- `subprocess.run` mocked for Docker commands
- `httpx.get` mocked for Ollama API
- `socket.socket` mocked for port checks
- `urllib.request` mocked for HTTP health endpoints

## Troubleshooting

### Common Issues

| Issue | Resolution |
|-------|------------|
| "Docker not found" | Install Docker Desktop; ensure daemon running |
| "Docker daemon not responsive" | Start Docker Desktop; check `docker info` |
| "VAULT_PATH not set" | Edit `.env` with absolute path to vault |
| "Vault validation failed" | Path must contain `.obsidian/` directory |
| "Ollama connection failed" | `ollama serve`; check `OLLAMA_HOST` |
| "Model not found" | `ollama pull nomic-embed-text` |
| "Port 8080 in use" | Check `docker ps`; stop conflicting container |
| "Compose config invalid" | Check `docker compose config` output |
| "Permission denied (Windows)" | Run terminal as Administrator |

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Error (preflight failure, Docker error, etc.) |
| 2 | Warning (doctor: non-critical issues) |
| 130 | Interrupted (Ctrl+C) |

## Files Created/Modified

### Created
- `memora/lifecycle/__init__.py`
- `memora/lifecycle/cli.py` (~1000 lines)
- `tests/test_lifecycle_cli.py` (22 tests)
- `install.ps1` (PowerShell installer)
- `install.bat` (CMD installer)
- `docs/LIFECYCLE_MANAGEMENT.md` (this file)

### Modified
- `pyproject.toml` → Added `memora = "memora.cli:app"` entry point
- `memora/cli.py` → Added lifecycle callback with 7 flags + subcommands
- `memora/lifecycle/__init__.py` → Exports orchestration functions
- `README.md` → Updated Quick Start, CLI commands table
- `docs/INSTALLATION.md` → Added lifecycle commands, Windows installer

## Remaining Limitations

1. **Docker Required**: Full startup requires Docker (not available in CI test env)
2. **Windows Testing**: Installer scripts created but need Windows validation
3. **Ollama Auto-Start**: Provides controlled mechanism but doesn't auto-install
4. **Firewall**: No automatic Windows firewall rules (per requirements)
5. **TLS/SSL**: HTTP only; no built-in HTTPS termination
6. **Multi-user**: Single-user PATH; system-wide requires admin