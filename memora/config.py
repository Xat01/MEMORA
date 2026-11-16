"""
MEMORA Configuration Module

Centralized configuration using Pydantic Settings with environment variable support.
"""

import logging
import os
from pathlib import Path
from typing import Optional
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# Module-level logger
logger = logging.getLogger("memora.config")


def find_project_root() -> Path:
    """Find the MEMORA project root by locating .env or pyproject.toml."""
    # Start from this file's directory and walk up
    current = Path(__file__).resolve().parent
    while current != current.parent:
        if (current / ".env").exists() or (current / "pyproject.toml").exists():
            return current
        current = current.parent
    # Fallback: assume project root is parent of memora package
    return Path(__file__).resolve().parent.parent


PROJECT_ROOT = find_project_root()


def resolve_path(path: Path, base: Path = PROJECT_ROOT) -> Path:
    """Resolve a path against the project root if it's relative.

    Handles Unix-style absolute paths (starting with '/') on Windows
    by treating them as absolute (for WSL/cross-platform compatibility).
    """
    # On Windows, Path.is_absolute() returns False for paths starting with '/'
    # Treat Unix-style absolute paths as absolute on all platforms
    if path.is_absolute() or (os.name == "nt" and str(path).startswith("/")):
        return path
    return (base / path).resolve()


class MemoraConfig(BaseSettings):
    """Main configuration for MEMORA memory infrastructure."""

    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # =========================================================================
    # REQUIRED: Vault Path
    # =========================================================================
    vault_path: Path = Field(
        description="Absolute path to Obsidian vault (folder containing .obsidian/)",
        validation_alias="VAULT_PATH",
    )

    # =========================================================================
    # Storage Paths
    # =========================================================================
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

    # =========================================================================
    # Embedding Configuration
    # =========================================================================
    embedding_model: str = Field(
        default="nomic-embed-text",
        description="Ollama embedding model name",
        validation_alias="EMBEDDING_MODEL",
    )

    embedding_dimensions: int = Field(
        default=768,
        description="Embedding model output dimensions",
        validation_alias="EMBEDDING_DIMENSIONS",
    )

    ollama_host: str = Field(
        default="http://localhost:11434",
        description="Ollama API endpoint",
        validation_alias="OLLAMA_HOST",
    )

    # =========================================================================
    # Chunking Configuration
    # =========================================================================
    chunk_size: int = Field(
        default=512,
        description="Token chunk size for splitting",
        validation_alias="CHUNK_SIZE",
        ge=100,
        le=2000,
    )

    chunk_overlap: int = Field(
        default=50,
        description="Token overlap between chunks",
        validation_alias="CHUNK_OVERLAP",
        ge=0,
        le=200,
    )

    # =========================================================================
    # Search Configuration
    # =========================================================================
    default_search_k: int = Field(
        default=10,
        description="Default number of search results",
        validation_alias="DEFAULT_SEARCH_K",
        ge=1,
        le=100,
    )

    hybrid_rrf_k: int = Field(
        default=60,
        description="Reciprocal Rank Fusion constant",
        validation_alias="HYBRID_RRF_K",
        ge=1,
        le=200,
    )

    # =========================================================================
    # MCP Server Configuration
    # =========================================================================
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
        ge=1024,
        le=65535,
    )

    # =========================================================================
    # Logging
    # =========================================================================
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

    # -------------------------------------------------------------------------
    # Computed Properties
    # -------------------------------------------------------------------------

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
        if not self.vault_path.exists():
            return False
        obsidian_dir = self.vault_path / ".obsidian"
        return obsidian_dir.exists() and obsidian_dir.is_dir()

    def log_resolved_paths(self) -> None:
        """Log resolved storage paths for startup diagnostics."""
        logger.info(f"Project root: {PROJECT_ROOT}")
        logger.info(f"Resolved vault_path: {self.vault_path}")
        logger.info(f"Resolved chroma_path: {self.chroma_path}")
        logger.info(f"Resolved sqlite_path: {self.sqlite_path}")
        logger.info(f"Resolved data_dir: {self.data_dir}")
        if self.log_file:
            logger.info(f"Resolved log_file: {self.log_file}")

    @model_validator(mode="after")
    def resolve_paths(self) -> "MemoraConfig":
        """Resolve all relative paths against project root after settings are loaded."""
        # Resolve storage paths
        self.chroma_path = resolve_path(self.chroma_path)
        self.sqlite_path = resolve_path(self.sqlite_path)
        if self.log_file:
            self.log_file = resolve_path(self.log_file)
        # Note: vault_path is typically absolute (from VAULT_PATH), but resolve if relative
        self.vault_path = resolve_path(self.vault_path)
        return self


# Global config instance
_config: Optional[MemoraConfig] = None


def get_config() -> MemoraConfig:
    """Get global configuration instance (singleton)."""
    global _config
    if _config is None:
        _config = MemoraConfig()
    return _config


def set_config(config: MemoraConfig) -> None:
    """Set global configuration instance."""
    global _config
    _config = config