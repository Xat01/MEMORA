# MEMORA Quick Reference — Key Changes (Nov 2026)

## Configuration Loading

### Old (Contaminated)
```python
PROJECT_ROOT = find_project_root()  # Global, set at import

class MemoraConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env")  # BAKED IN at class def
    )

_config = MemoraConfig()  # Singleton

def load_config(project_root):
    PROJECT_ROOT = project_root  # Try to override
    _config = None
    return get_config()  # Still uses original env_file!
```

### New (Isolated)
```python
def create_config_class(project_root: Path):
    """Factory: new class per project_root."""
    env_file_path = str(project_root / ".env")
    
    class ProjectMemoraConfig(BaseSettings):
        model_config = SettingsConfigDict(
            env_file=env_file_path,  # Evaluated per call
            ...
        )
    return ProjectMemoraConfig

def load_config(project_root: Path):
    return create_config_class(project_root)()

def get_config():  # Backward compat
    global _config
    if _config is None:
        _config = create_config_class(DEFAULT_PROJECT_ROOT)()
    return _config
```

---

## Windows Path Handling

```python
def resolve_path(path: Path, base: Path) -> Path:
    path_str = str(path)
    is_absolute = (
        path.is_absolute() or
        (os.name == "nt" and path_str.startswith("/")) or
        (os.name == "nt" and len(path_str) >= 2 and 
         path_str[1] == ":" and path_str[2] in ("/", "\\"))
    )
    return path if is_absolute else (base / path).resolve()
```

**Accepted formats (Windows):**
- `C:/Users/.../My Vault` ✅ (forward slashes)
- `/host_mnt/c/Users/...` ✅ (Docker Desktop)
- `C:\Users\...` ❌ (backslashes → ERROR)

---

## Lifecycle Commands

| Command | Description |
|---------|-------------|
| `memora --start` | Full preflight → build → up → health → verify |
| `memora --stop` | Graceful down (preserves volumes) |
| `memora --restart` | Restart → health → verify |
| `memora --status` | Docker, containers, MCP, Ollama, storage, vault |
| `memora --doctor` | 11 diagnostic checks |
| `memora --logs` | Service logs (follow/tail) |
| `memora --version` | Version info |
| `memora --purge --confirm-destroy` | DESTRUCTIVE: removes all volumes |

---

## Preflight Checks

| Category | Checks |
|----------|--------|
| System | OS, Python ≥3.10, Docker CLI, Docker daemon, Docker Compose, permissions |
| Config | compose.yml, Dockerfile, .env.docker, .env, VAULT_PATH, OLLAMA_MODE, volumes, compose config |
| Ollama | Host mode: Docker host gateway + local host; Container mode: container health |
| Network | Port 8080 (smart detection of existing memora-http) |
| Storage | Writable dirs, volume mounts, vault accessibility |

---

## Output Format (memora --start)

```
MEMORA STARTUP

  Docker: Available
  Ollama: Available
  Configuration: Valid
  SQLite: Healthy
  ChromaDB: Healthy
  MCP Server: Healthy

MEMORA is ready at http://127.0.0.1:8080
```

---

## Key Files

| File | Purpose |
|------|---------|
| `memora/config.py` | Factory pattern, `load_config()`, `get_config()`, `resolve_path()` |
| `memora/lifecycle/cli.py` | Orchestration, preflight, compose management |
| `memora/mcp/server.py` | MCP server with health endpoints |
| `memora/diagnostics.py` | `memora --doctor` implementation |
| `tests/test_lifecycle_cli.py` | 54 tests (14 new regression) |
| `docker-compose.yml` | Dual profile: http, ollama |
| `.env.docker` | Docker deployment template |
| `docs/LIFECYCLE_MANAGEMENT.md` | Full lifecycle docs |
