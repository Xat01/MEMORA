# MEMORA Installation Guide

## Prerequisites

### System Requirements
- **Python**: 3.10 or higher
- **Operating System**: Linux, macOS, or Windows (WSL2 recommended on Windows)
- **Obsidian**: Vault with `.obsidian` folder
- **Docker**: Docker Desktop (Windows/macOS) or Docker Engine + Compose plugin (Linux) — *required for `memora --start`*

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

## Installation Methods

### Method 1: Docker Lifecycle Manager (Recommended for Production)

The new `memora --start` command provides a complete production deployment with preflight validation.

#### Windows Installation (One-Command Setup)

**PowerShell (Run as Administrator for PATH):**
```powershell
# Clone or download MEMORA, then run:
.\install.ps1
```

**CMD (Run as Administrator):**
```cmd
install.bat
```

The installer will:
1. Create a persistent installation in `%LOCALAPPDATA%\MEMORA`
2. Set up a Python virtual environment
3. Install MEMORA in editable mode
4. Create wrapper scripts (`memora.bat`, `memora.ps1`)
5. Add to user PATH
6. Verify the installation

After installation, restart your terminal and run:
```powershell
# Configure your vault path
copy %LOCALAPPDATA%\MEMORA\.env.example %LOCALAPPDATA%\MEMORA\.env
# Edit VAULT_PATH in the .env file

# Start MEMORA with full validation
memora --start
```

#### Linux/macOS Installation
```bash
# Clone repository
git clone <repository-url>
cd MEMORA

# Install in development mode
pip install -e .

# Configure environment
cp .env.docker .env
# Edit VAULT_PATH in .env

# Start with full preflight validation
memora --start
```

---

### Method 2: Local Development Installation

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
VAULT_PATH=/mnt/c/Users/user\Documents\MyVault
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

---

## Lifecycle Management Commands

The new unified CLI provides lifecycle management through direct flags:

```bash
# Start with full preflight validation (Docker)
memora --start

# Skip preflight checks (faster startup)
memora --start --skip-preflight

# Skip Docker image build
memora --start --no-build

# Gracefully stop services
memora --stop

# Stop and remove volumes (DANGEROUS - data loss)
memora --stop -v

# Restart with health verification
memora --restart

# Comprehensive status report
memora --status

# System diagnostics
memora --doctor
memora --doctor --json      # JSON output
memora --doctor --verbose   # Detailed output

# Service logs
memora --logs
memora --logs -f            # Follow output
memora --logs -n 50         # Last 50 lines

# Version information
memora --version
```

---

## Windows-Specific Notes

### Windows Installation Details

The PowerShell installer (`install.ps1`) and batch installer (`install.bat`) provide:

1. **Persistent Installation**: Installs to `%LOCALAPPDATA%\MEMORA`
2. **Virtual Environment**: Creates `.venv` in the install directory
3. **Wrapper Scripts**: Creates `memora.bat` (CMD) and `memora.ps1` (PowerShell)
4. **PATH Integration**: Adds scripts directory to user PATH
5. **Verification**: Runs `memora --version` to confirm installation

### Running from Any Directory

After installation, `memora` works from any directory:
- The wrapper scripts set `MEMORA_HOME` automatically
- The CLI discovers the project root via `MEMORA_HOME` env var
- Falls back to finding `pyproject.toml` or `.env` in CWD
- Falls back to the package installation location

```powershell
# Use from anywhere - no configuration needed
cd C:\MyProject
memora --start
memora --status
memora search "my query"
```

### Wrapper Scripts (Created by Installer)

The installer creates two wrapper scripts in `%LOCALAPPDATA%\MEMORA\scripts\`:

**`memora.bat` (for CMD):**
```bat
@echo off
set MEMORA_HOME=C:\Users\you\AppData\Local\MEMORA
call "C:\Users\you\AppData\Local\MEMORA\.venv\Scripts\activate.bat" >nul 2>&1
memora %*
```

**`memora.ps1` (for PowerShell):**
```powershell
# MEMORA PowerShell Wrapper
$env:MEMORA_HOME = "C:\Users\you\AppData\Local\MEMORA"
& "C:\Users\you\AppData\Local\MEMORA\.venv\Scripts\Activate.ps1" > $null 2>&1
& memora @args
```

These wrappers:
1. Set `MEMORA_HOME` to the installation directory
2. Activate the virtual environment
3. Execute the `memora` command from the venv

---

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

For Docker-based HTTP transport:
```json
{
  "mcpServers": {
    "memora": {
      "command": "docker",
      "args": ["run", "--rm", "-i", "memora:latest", "memora-server", "stdio"],
      "env": {
        "VAULT_PATH": "/vault"
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

---

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

---

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

#### "Docker not found" (for `memora --start`)
- Install Docker Desktop from https://docker.com/products/docker-desktop
- Ensure Docker daemon is running
- Verify: `docker info`

### Logs
Check logs for detailed errors:
```bash
# Default log location (if configured)
cat logs/memora.log

# Docker container logs
docker logs memora-http
```

---

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

# Windows: Remove installed version
rm -rf %LOCALAPPDATA%\MEMORA
# Remove from PATH via System Properties > Environment Variables
```

## Next Steps

- Read [CONFIGURATION.md](CONFIGURATION.md) for advanced settings
- Read [ARCHITECTURE.md](ARCHITECTURE.md) for system design
- Explore the [MCP tools](ARCHITECTURE.md#mcp-server) available