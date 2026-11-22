# mem_plugIN_update - Plugin Architecture Proposal

**Date**: 2025-11-22
**Status**: Proposal
**Related**: MEMORA architecture, plugin system design

## Plugin Architecture Proposal

### Core Concept
```
memora-core (minimal)
├── config.py          # Configuration only
├── plugin_manager.py  # Plugin discovery/loading
├── interfaces.py      # Abstract base classes
└── cli.py            # Minimal CLI, delegates to plugins
```

### Plugin Interface

```python
# memora/interfaces.py
from abc import ABC, abstractmethod
from typing import Any
from pathlib import Path

class VaultProvider(ABC):
    """Discover and read vault files"""
    @abstractmethod
    def discover_vaults(self) -> list[Path]: ...
    
    @abstractmethod
    def read_files(self, vault_path: Path) -> list[FileContent]: ...

class EmbeddingProvider(ABC):
    """Generate embeddings"""
    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]: ...
    
    @property
    @abstractmethod
    def dimensions(self) -> int: ...

class VectorStore(ABC):
    """Vector storage backend"""
    @abstractmethod
    def add(self, vectors: list[list[float]], metadata: list[dict]): ...
    
    @abstractmethod
    def search(self, query: list[float], k: int) -> list[SearchResult]: ...

class CLICommand(ABC):
    """Custom CLI commands"""
    @property
    @abstractmethod
    def name(self) -> str: ...
    
    @abstractmethod
    def execute(self, args: list[str]) -> int: ...
```

### Plugin Structure

```
memora/plugins/
├── builtin/
│   ├── vault_fs.py        # Filesystem vault provider
│   ├── ollama_embeddings.py
│   ├── chromadb_store.py
│   ├── sqlite_store.py
│   └── commands.py        # ingest, search, doctor, etc.
├── my_custom/
│   └── my_vault.py        # Custom vault provider
```

### Plugin Registration

```python
# memora/plugin_manager.py
from typing import Dict, Type
from .interfaces import VaultProvider, EmbeddingProvider, VectorStore, CLICommand

class PluginManager:
    def __init__(self):
        self.vault_providers: Dict[str, Type[VaultProvider]] = {}
        self.embedding_providers: Dict[str, Type[EmbeddingProvider]] = {}
        self.vector_stores: Dict[str, Type[VectorStore]] = {}
        self.commands: Dict[str, Type[CLICommand]] = {}
    
    def register_vault_provider(self, name: str, provider: Type[VaultProvider]):
        self.vault_providers[name] = provider
    
    def get_vault_provider(self, name: str) -> VaultProvider:
        return self.vault_providers[name]()
```

### Usage

```python
# config.py - declarative
PLUGINS = {
    "vault": "builtin.fs",
    "embeddings": "builtin.ollama",
    "vector_store": "builtin.chromadb",
    "commands": ["builtin.ingest", "builtin.search", "builtin.doctor"]
}

# Or custom
PLUGINS = {
    "vault": "my_company.custom_vault",
    "embeddings": "my_company.openai_embeddings",
    "commands": ["builtin.ingest", "my_company.custom_cmd"]
}
```

---

## Connected Nodes

- [[MEMORA Architecture]]
- [[Plugin System Design]]
- [[Vault Discovery]]
- [[Embedding Providers]]
- [[Vector Stores]]
- [[CLI Commands]]
- [[Configuration System]]
- [[STDIO Mode]]
- [[Docker Deployment]]
- [[MEMORA Architecture]]
