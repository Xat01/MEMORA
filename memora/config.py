"""
MEMORA Configuration Module

Centralized configuration using Pydantic Settings with environment variable support.
Supports multiple embedding providers (Ollama, OpenAI-compatible, custom).
"""

import logging
import os
from pathlib import Path
from typing import Annotated, Any, List, Optional
from pydantic import Field, model_validator, BeforeValidator
from pydantic_settings import BaseSettings, SettingsConfigDict


# Module-level logger
logger = logging.getLogger("memora.config")


def _coerce_empty_to_none(v: Any) -> Optional[str]:
    """Coerce empty strings to None."""
    if v is None:
        return None
    if isinstance(v, str):
        v = v.strip()
        return v if v else None
    return v


def _coerce_path(v: Any) -> Optional[Path]:
    """Coerce vault path value, treating empty strings as None."""
    if v is None:
        return None
    if isinstance(v, str):
        v = v.strip()
        if not v:
            return None
        return Path(v)
    if isinstance(v, Path):
        return v
    return None


def find_project_root(start: Optional[Path] = None) -> Path:
    """Find the MEMORA project root by locating .env or pyproject.toml.
    
    Checks upwards from the given path (or current working directory).
    If no project root is found, falls back to current working directory.
    """
    current = (start or Path.cwd()).resolve()
    while current != current.parent:
        if (current / ".env").exists() or (current / "pyproject.toml").exists():
            return current
        current = current.parent
    return Path.cwd().resolve()


def resolve_path(path: Path, base: Path) -> Path:
    """Resolve a path against the given base if it's relative.

    Handles Unix-style absolute paths (starting with '/') on Windows
    and Windows drive-letter paths (C:/, D:/) as absolute.
    """
    path_str = str(path)
    is_absolute = (
        path.is_absolute() or
        (os.name == "nt" and path_str.startswith("/")) or
        (os.name == "nt" and len(path_str) >= 2 and path_str[1] == ":" and
         path_str[2:3] in ("/", "\\"))
    )
    if is_absolute:
        return path
    return (base / path).resolve()


def discover_obsidian_vaults(search_paths: Optional[List[Path]] = None,
                              max_depth: int = 3) -> List[Path]:
    """Discover Obsidian vaults by searching for .obsidian directories."""
    if search_paths is None:
        search_paths = []
        # Common locations
        home = Path.home()
        for loc in [
            Path.cwd(),
            home / "Documents",
            home / "Obsidian",
            home / "vaults",
            home / "Notes",
            home / "Second Brain",
        ]:
            try:
                if loc.exists():
                    search_paths.append(loc)
            except (PermissionError, OSError):
                pass
        # Windows-specific
        if os.name == "nt":
            onedrive = os.environ.get("OneDrive")
            if onedrive:
                try:
                    od_doc = Path(onedrive) / "Documents"
                    if od_doc.exists():
                        search_paths.append(od_doc)
                except (PermissionError, OSError):
                    pass

    skip_dirs = {'.git', 'node_modules', '__pycache__', '.venv', 'venv',
                 'build', 'dist', '.cache', 'tmp'}
    vaults = []

    def _search(root: Path, depth: int):
        if depth < 0:
            return
        try:
            for item in root.iterdir():
                if item.name == ".obsidian" and item.is_dir():
                    vaults.append(root.resolve())
                    return
                if item.is_dir() and item.name not in skip_dirs and not item.name.startswith('.'):
                    _search(item, depth - 1)
        except (PermissionError, OSError):
            pass

    for sp in search_paths:
        _search(sp, max_depth)

    return list(dict.fromkeys(vaults))  # dedupe preserving order


def create_config_class(project_root: Path):
    """Create a MemoraConfig class bound to a specific project root.

    Factory pattern ensures env_file is evaluated per project root,
    avoiding singleton contamination.
    """
    env_file_path = str(project_root / ".env")

    class ProjectMemoraConfig(BaseSettings):
        """MEMORA configuration — supports Ollama, OpenAI-compatible, and custom providers."""

        model_config = SettingsConfigDict(
            env_file=env_file_path,
            env_file_encoding="utf-8",
            case_sensitive=False,
            extra="ignore",
        )

        # =====================================================================
        # Vault Path (Optional — auto-discovered if not provided)
        # =====================================================================
        vault_path: Annotated[Optional[Path], BeforeValidator(_coerce_path)] = Field(
            default=None,
            description="Absolute path to Obsidian vault (folder containing .obsidian/). Auto-discovered if not provided.",
        )

        # =====================================================================
        # Storage Paths
        # =====================================================================
        chroma_path: Path = Field(
            default=Path("./data/chromadb"),
            description="ChromaDB persistence directory",
            validation_alias="CHROMA_PATH",
        )

        sqlite_path: Path = Field(
            default=Path("./data/memora.db"),
            description="SQLite database path",
            validation_alias="SQLITE_PATH",
        )

        # =====================================================================
        # Embedding Provider Selection
        # =====================================================================
        embedding_provider: str = Field(
            default="ollama",
            description="Embedding provider: 'ollama', 'openai', or fully-qualified class name",
            validation_alias="EMBEDDING_PROVIDER",
        )

        embedding_model: str = Field(
            default="nomic-embed-text",
            description="Embedding model name (provider-specific)",
            validation_alias="EMBEDDING_MODEL",
        )

        embedding_dimensions: int = Field(
            default=768,
            description="Embedding model output dimensions",
            validation_alias="EMBEDDING_DIMENSIONS",
        )

        # =====================================================================
        # Ollama-specific
        # =====================================================================
        ollama_host: str = Field(
            default="http://localhost:11434",
            description="Ollama API endpoint",
            validation_alias="OLLAMA_HOST",
        )

        # =====================================================================
        # OpenAI-compatible provider
        # =====================================================================
        embedding_api_key: Annotated[Optional[str], BeforeValidator(_coerce_empty_to_none)] = Field(
            default=None,
            description="API key for OpenAI-compatible embedding provider",
            validation_alias="EMBEDDING_API_KEY",
        )

        embedding_api_base: Annotated[Optional[str], BeforeValidator(_coerce_empty_to_none)] = Field(
            default=None,
            description="Base URL for OpenAI-compatible API (e.g., https://api.openai.com/v1)",
            validation_alias="EMBEDDING_API_BASE",
        )

        # =====================================================================
        # Chunking Configuration
        # =====================================================================
        chunk_size: int = Field(
            default=512,
            description="Token chunk size for splitting",
            validation_alias="CHUNK_SIZE",
            ge=100, le=2000,
        )

        chunk_overlap: int = Field(
            default=50,
            description="Token overlap between chunks",
            validation_alias="CHUNK_OVERLAP",
            ge=0, le=200,
        )

        # =====================================================================
        # Search Configuration
        # =====================================================================
        default_search_k: int = Field(
            default=10,
            description="Default number of search results",
            validation_alias="DEFAULT_SEARCH_K",
            ge=1, le=100,
        )

        hybrid_rrf_k: int = Field(
            default=60,
            description="Reciprocal Rank Fusion constant",
            validation_alias="HYBRID_RRF_K",
            ge=1, le=200,
        )

        # =====================================================================
        # MCP Server Configuration
        # =====================================================================
        mcp_transport: str = Field(
            default="stdio",
            description="MCP transport protocol (stdio or http)",
            validation_alias="MCP_TRANSPORT",
        )

        mcp_host: str = Field(
            default="127.0.0.1",
            description="MCP HTTP host",
            validation_alias="MCP_HOST",
        )

        mcp_port: int = Field(
            default=8080,
            description="MCP HTTP port",
            validation_alias="MCP_PORT",
            ge=1024, le=65535,
        )

        # =====================================================================
        # Logging
        # =====================================================================
        log_level: str = Field(
            default="INFO",
            description="Logging level",
            validation_alias="LOG_LEVEL",
        )

        log_file: Optional[Path] = Field(
            default=None,
            description="Log file path (optional)",
            validation_alias="LOG_FILE",
        )

        # -----------------------------------------------------------------
        # Computed Properties
        # -----------------------------------------------------------------

        @property
        def data_dir(self) -> Path:
            """Data directory (parent of sqlite_path)."""
            return self.sqlite_path.parent

        def ensure_dirs(self) -> None:
            """Create necessary directories."""
            self.data_dir.mkdir(parents=True, exist_ok=True)
            self.chroma_path.mkdir(parents=True, exist_ok=True)
            if self.log_file:
                self.log_file.parent.mkdir(parents=True, exist_ok=True)

        def validate_vault(self) -> bool:
            """Validate that vault path exists and contains .obsidian folder."""
            if self.vault_path is None or not self.vault_path.exists():
                return False
            obsidian_dir = self.vault_path / ".obsidian"
            return obsidian_dir.exists() and obsidian_dir.is_dir()

        def log_resolved_paths(self) -> None:
            """Log resolved storage paths for startup diagnostics."""
            logger.info(f"Project root: {project_root}")
            logger.info(f"Resolved vault_path: {self.vault_path}")
            logger.info(f"Resolved chroma_path: {self.chroma_path}")
            logger.info(f"Resolved sqlite_path: {self.sqlite_path}")
            logger.info(f"Resolved data_dir: {self.data_dir}")
            if self.log_file:
                logger.info(f"Resolved log_file: {self.log_file}")

        @model_validator(mode="after")
        def resolve_paths(self) -> "ProjectMemoraConfig":
            """Resolve relative paths and auto-discover vault."""
            # Resolve storage paths
            self.chroma_path = resolve_path(self.chroma_path, project_root)
            self.sqlite_path = resolve_path(self.sqlite_path, project_root)
            if self.log_file:
                self.log_file = resolve_path(self.log_file, project_root)
            # Resolve vault path
            if self.vault_path is not None:
                resolved = resolve_path(self.vault_path, project_root)
                try:
                    if resolved.exists() and (resolved / ".obsidian").exists():
                        self.vault_path = resolved
                    else:
                        logger.warning(f"Configured vault path not valid: {resolved}")
                        self.vault_path = None
                except (PermissionError, OSError):
                    # In restricted or sandboxed environments, preserve the configured path
                    self.vault_path = resolved
            # Auto-discover if not set
            if self.vault_path is None:
                vaults = discover_obsidian_vaults()
                if vaults:
                    self.vault_path = vaults[0]
                    logger.info(f"Auto-discovered vault: {self.vault_path}")
            return self

    return ProjectMemoraConfig


# =========================================================================
# Global config (backward compatibility)
# =========================================================================
_DEFAULT_PROJECT_ROOT = find_project_root()
_MemoraConfig = create_config_class(_DEFAULT_PROJECT_ROOT)
_config: Optional[_MemoraConfig] = None


def get_config() -> _MemoraConfig:
    """Get global configuration instance (singleton for default project root)."""
    global _config
    if _config is None:
        _config = _MemoraConfig()
    return _config


def set_config(config: _MemoraConfig) -> None:
    """Set global configuration instance."""
    global _config
    _config = config


def load_config(project_root: Path):
    """Load configuration from a specific project root (isolated)."""
    config_class = create_config_class(project_root)
    return config_class()


# Export for backward compatibility
MemoraConfig = _MemoraConfig
PROJECT_ROOT = _DEFAULT_PROJECT_ROOT
