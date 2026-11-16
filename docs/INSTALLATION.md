# MEMORA Installation Guide

## Prerequisites

### System Requirements
- **Python**: 3.10 or higher
- **Operating System**: Linux, macOS, or Windows (WSL2 recommended on Windows)
- **Obsidian**: Vault with `.obsidian` folder

### Required Software

#### 1. Ollama (Local Embeddings)
```bash
# Linux/macOS
curl -fsSL https://ollama.ai/install.sh | sh

# Windows
# Download from https://ollama.ai/download
```

Start Ollama service:
```bash
ollama serve
```

Pull the embedding model:
```bash
ollama pull nomic-embed-text
```

Verify installation:
```bash
ollama list
# Should show nomic-embed-text
```

#### 2. Python Dependencies
```bash
# Create virtual environment (recommended)
python3 -m venv .venv
source .venv/bin/activate  # Linux/macOS
# .venv\Scripts\activate   # Windows

# Install MEMORA dependencies
pip install -r requirements.txt
```

#### 3. ChromaDB
Installed automatically via `requirements.txt` (chromadb>=0.5.0)

## Installation Steps

### 1. Clone/Download MEMORA
```bash
# If using git
git clone <repository-url>
cd MEMORA

# Or download and extract to desired location
```

### 2. Install Python Dependencies
```bash
pip install -r requirements.txt
```

### 3. Configure Environment
```bash
# Copy example configuration
cp .env.example .env

# Edit .env with your settings
# Required: VAULT_PATH
```

### 4. Configure Vault Path
Edit `.env` and set `VAULT_PATH` to your Obsidian vault:

```env
# Linux/macOS example
VAULT_PATH=/home/user/Documents/MyVault

# Windows example
VAULT_PATH=C:\Users\user\Documents\MyVault

# WSL2 example (accessing Windows vault)
VAULT_PATH=/mnt/c/Users/user/Documents/MyVault
```

**Important**: The path must point to the folder containing `.obsidian/`

### 5. Verify Installation
```bash
# Run full system diagnostics (recommended)
memora doctor

# Or with JSON output for automation
memora doctor --json

# Check configuration
python -c "from memora.config import get_config; c=get_config(); print('Vault:', c.vault_path); print('Valid:', c.validate_vault())"

# Test Ollama connection
python -c "from memora.embeddings.ollama_provider import OllamaProvider; p=OllamaProvider(); print('Ollama:', p.health_check())"

# Test ChromaDB
python -c "from memora.storage.vector_store import VectorStore; v=VectorStore(); print('ChromaDB:', v.get_collection_info())"
```

### 6. Run Initial Indexing
```bash
# Full initial indexing
python -m memora.ingestion.indexer

# Or with progress output
python -c "
from memora.ingestion.indexer import create_indexer
def progress(msg, current, total):
    print(f'[{current}/{total}] {msg}')
indexer = create_indexer(progress_callback=progress)
stats = indexer.index()
print(f'Indexed {stats.files_indexed} files, {stats.chunks_created} chunks in {stats.duration_seconds:.1f}s')
"
```

### 7. Start MCP Server (for Claude Desktop)
```bash
# Stdio transport (for Claude Desktop)
python -m memora.mcp.server

# HTTP transport (for network access)
python -m memora.mcp.server http 127.0.0.1 8080
```

## Claude Desktop Integration

### 1. Configure MCP Server
Add to your Claude Desktop configuration (`claude_desktop_config.json`):

**Linux**: `~/.config/claude/claude_desktop_config.json`
**macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
**Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "memora": {
      "command": "python",
      "args": ["-m", "memora.mcp.server"],
      "cwd": "/full/path/to/MEMORA",
      "env": {
        "VAULT_PATH": "/full/path/to/your/vault"
      }
    }
  }
}
```

### 2. Restart Claude Desktop
The MEMORA tools will appear in the tools panel.

### 3. Test in Claude
Try these commands in Claude:
- "Search my vault for 'machine learning'"
- "Memorize this: 'The capital of France is Paris' with tags ['geography']"
- "Get context for 'project architecture'"
- "List my indexed sources"

## Development Installation

For development with editable install:
```bash
pip install -e .
```

Run tests:
```bash
pytest tests/ -v
```

Run with watch mode for continuous indexing:
```bash
python -m memora.ingestion.indexer --watch
```

## Troubleshooting

### Common Issues

#### "VAULT_PATH not set"
```bash
# Check .env file exists and has VAULT_PATH
cat .env | grep VAULT_PATH
```

#### "Vault validation failed"
- Ensure path is absolute
- Ensure `.obsidian` folder exists in that path
- Check permissions

#### "Ollama connection failed"
```bash
# Check Ollama is running
curl http://localhost:11434/api/tags

# Check model is pulled
ollama list | grep nomic-embed-text
```

#### "ChromaDB error"
```bash
# Reset ChromaDB
rm -rf data/chromadb
# Re-run indexing
```

#### "Module not found" errors
```bash
# Ensure virtual environment is activated
source .venv/bin/activate
pip install -r requirements.txt
```

#### "Permission denied" on Windows
- Run terminal as Administrator
- Or use WSL2 for better compatibility

### Logs
Check logs for detailed errors:
```bash
# Default log location (if configured)
cat logs/memora.log
```

## Updating MEMORA

```bash
# Pull latest changes
git pull

# Update dependencies
pip install -r requirements.txt --upgrade

# Re-index if embedding model changed
python -m memora.ingestion.indexer --full
```

## Uninstalling

```bash
# Remove virtual environment
rm -rf .venv

# Remove data (optional)
rm -rf data/

# Remove configuration
rm .env
```

## Next Steps

- Read [CONFIGURATION.md](CONFIGURATION.md) for advanced settings
- Read [ARCHITECTURE.md](ARCHITECTURE.md) for system design
- Explore the [MCP tools](ARCHITECTURE.md#mcp-server) available