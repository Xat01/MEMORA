# MEMORA Configuration Guide

## Overview

MEMORA is configured via environment variables in a `.env` file. All settings have sensible defaults except `VAULT_PATH` which is required.

## Configuration File

Create `.env` from the example:
```bash
cp .env.example .env
```

## Required Settings

### VAULT_PATH
**Required** — Absolute path to your Obsidian vault (the folder containing `.obsidian/`)

```env
# Linux/macOS
VAULT_PATH=/home/user/Documents/MyVault

# Windows
VAULT_PATH=C:\Users\user\Documents\MyVault

# WSL2 accessing Windows
VAULT_PATH=/mnt/c/Users/user/Documents/MyVault
```

**Validation**: The path must exist and contain a `.obsidian` folder.

## Storage Settings

### CHROMA_PATH
ChromaDB persistence directory.
```env
CHROMA_PATH=./data/chromadb
```
- Relative to project root or absolute path
- Created automatically if missing

### SQLITE_PATH
SQLite database file path.
```env
SQLITE_PATH=./data/memora.db
```
- Relative to project root or absolute path
- Parent directory created automatically

## Embedding Settings

### EMBEDDING_MODEL
Ollama embedding model name.
```env
EMBEDDING_MODEL=nomic-embed-text
```
**Recommended models**:
| Model | Dimensions | Size | Quality |
|-------|------------|------|---------|
| `nomic-embed-text` | 768 | ~274MB | Excellent (default) |
| `mxbai-embed-large` | 1024 | ~670MB | Best |
| `all-minilm` | 384 | ~90MB | Good, fast |
| `bge-m3` | 1024 | ~1.1GB | Multilingual |

Must be pulled in Ollama: `ollama pull <model-name>`

### EMBEDDING_DIMENSIONS
Output dimensions of the embedding model.
```env
EMBEDDING_DIMENSIONS=768
```
**Must match the model's actual dimensions**. Mismatch will cause errors.

### OLLAMA_HOST
Ollama API endpoint.
```env
OLLAMA_HOST=http://localhost:11434
```
- Default: local Ollama
- Can point to remote Ollama instance
- Include protocol (http/https) and port

## Chunking Settings

### CHUNK_SIZE
Target token size for each chunk.
```env
CHUNK_SIZE=512
```
- **Range**: 100-2000 tokens
- **Default**: 512 (~2000 characters)
- Larger = fewer chunks, more context per chunk
- Smaller = more chunks, finer retrieval granularity

### CHUNK_OVERLAP
Token overlap between adjacent chunks.
```env
CHUNK_OVERLAP=50
```
- **Range**: 0-200 tokens
- **Default**: 50 (~200 characters)
- Helps maintain context continuity
- Too high = redundant storage
- Too low = context fragmentation

## Search Settings

### DEFAULT_SEARCH_K
Default number of search results.
```env
DEFAULT_SEARCH_K=10
```
- **Range**: 1-100
- Can be overridden per query

### HYBRID_RRF_K
Reciprocal Rank Fusion constant for hybrid search.
```env
HYBRID_RRF_K=60
```
- **Range**: 1-200
- **Default**: 60 (standard RRF value)
- Lower = more weight to top-ranked results
- Higher = more balanced fusion

## MCP Server Settings

### MCP_TRANSPORT
Transport protocol for MCP server.
```env
MCP_TRANSPORT=stdio
```
Options:
- `stdio` — Standard input/output (for Claude Desktop)
- `http` — HTTP/SSE (for network access)

### MCP_HOST
HTTP server host (when using HTTP transport).
```env
MCP_HOST=127.0.0.1
```

### MCP_PORT
HTTP server port (when using HTTP transport).
```env
MCP_PORT=8080
```
- **Range**: 1024-65535

## Logging Settings

### LOG_LEVEL
Logging verbosity.
```env
LOG_LEVEL=INFO
```
Options: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`

### LOG_FILE
Log file path (optional).
```env
LOG_FILE=./logs/memora.log
```
- If set, logs written to file AND console
- Parent directory created automatically
- If empty, logs to console only

## Complete Example

```env
# =============================================================================
# MEMORA Configuration
# =============================================================================

# REQUIRED: Obsidian Vault Path
VAULT_PATH=/home/user/Documents/MyVault

# Storage
CHROMA_PATH=./data/chromadb
SQLITE_PATH=./data/memora.db

# Embeddings (Ollama)
EMBEDDING_MODEL=nomic-embed-text
EMBEDDING_DIMENSIONS=768
OLLAMA_HOST=http://localhost:11434

# Chunking
CHUNK_SIZE=512
CHUNK_OVERLAP=50

# Search
DEFAULT_SEARCH_K=10
HYBRID_RRF_K=60

# MCP Server
MCP_TRANSPORT=stdio
MCP_HOST=127.0.0.1
MCP_PORT=8080

# Logging
LOG_LEVEL=INFO
LOG_FILE=./logs/memora.log
```

## Configuration Validation

MEMORA validates configuration on startup:

```python
from memora.config import get_config

config = get_config()
print("Vault valid:", config.validate_vault())
print("Data dir:", config.data_dir)
print("Chroma path:", config.chroma_path)
```

## Runtime Configuration

Some settings can be overridden programmatically:

```python
from memora.config import MemoraConfig, set_config
from pathlib import Path

# Create custom config
custom_config = MemoraConfig(
    vault_path=Path("/custom/vault"),
    chunk_size=1024,
    chunk_overlap=100,
)
set_config(custom_config)
```

## Environment-Specific Configs

### Development
```env
LOG_LEVEL=DEBUG
LOG_FILE=./logs/memora-dev.log
CHUNK_SIZE=256  # Faster indexing for testing
```

### Production
```env
LOG_LEVEL=WARNING
LOG_FILE=./logs/memora-prod.log
CHUNK_SIZE=512
CHUNK_OVERLAP=50
```

### Large Vaults (>10K notes)
```env
CHUNK_SIZE=1024
CHUNK_OVERLAP=100
DEFAULT_SEARCH_K=20
HYBRID_RRF_K=60
```

### Multilingual Content
```env
EMBEDDING_MODEL=bge-m3
EMBEDDING_DIMENSIONS=1024
```

## Configuration Migration

When changing embedding model or dimensions:

1. Update `.env` with new values
2. Run full re-index:
   ```bash
   python -m memora.ingestion.indexer --full
   ```
3. Or via MCP:
   ```
   reindex full=true
   ```

**Note**: Changing embedding model requires full re-index as existing vectors are incompatible.

## Security Considerations

- Never commit `.env` to version control (in `.gitignore`)
- Use absolute paths for vault location
- Restrict file permissions on `.env`: `chmod 600 .env`
- Ollama runs locally by default — no API keys exposed

## System Diagnostics

MEMORA includes a built-in diagnostic command to verify your installation and configuration:

```bash
# Run all health checks
memora doctor

# Output as JSON (for scripts/CI)
memora doctor --json

# Verbose output with details
memora doctor --verbose
```

The doctor checks:
- **Python Environment** — Version compatibility (3.10+)
- **Dependencies** — All required packages installed
- **Configuration** — VAULT_PATH, paths, embedding dimensions
- **Ollama Connectivity** — Server reachable
- **Embedding Model** — Required model available in Ollama
- **ChromaDB** — Vector store accessible, metadata matches config
- **SQLite** — Database accessible, integrity check, WAL mode
- **Obsidian Vault** — Valid vault with .obsidian folder
- **Embedding Pipeline** — End-to-end embedding generation
- **MCP Configuration** — MCP package and transport config
- **Storage** — Directories writable, sufficient disk space

**Exit codes**: 0 = all PASS, 1 = any FAIL, 2 = WARN (no FAIL)

## Troubleshooting Config Issues

### "VAULT_PATH not set"
- Ensure `.env` exists in project root
- Check `VAULT_PATH` line is uncommented
- Verify no trailing spaces

### "Embedding dimension mismatch"
- Verify `EMBEDDING_DIMENSIONS` matches model
- Run `ollama show <model>` to check dimensions
- Re-index after fixing

### "Ollama connection refused"
- Check `OLLAMA_HOST` is correct
- Ensure Ollama service is running: `ollama serve`
- Test: `curl $OLLAMA_HOST/api/tags`

### "Permission denied on vault"
- Check vault path permissions
- Ensure user has read access to vault folder
- On WSL2: check Windows file permissions