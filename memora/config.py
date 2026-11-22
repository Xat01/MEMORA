"""
MEMORA Configuration Module

Centralized configuration using Pydantic Settings with environment variable support.
"""

import logging
import os
from pathlib import Path
from typing import Annotated, Optional, List, Any
from pydantic import Field, model_validator, BeforeValidator
from pydantic_settings import BaseSettings, SettingsConfigDict


# Module-level logger
logger = logging.getLogger("memora.config")


def _coerce_vault_path(v: Any) -> Optional[Path]:
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
    """Find the MEMORA project root by locating .env or pyproject.toml."""
    # Start from given path or this file's directory and walk up
    current = (start or Path(__file__).resolve().parent).resolve()
    while current != current.parent:
        if (current / ".env").exists() or (current / "pyproject.toml").exists():
            return current
        current = current.parent
    # Fallback: assume project root is parent of memora package
    return Path(__file__).resolve().parent.parent


def resolve_path(path: Path, base: Path) -> Path:
    """Resolve a path against the given base if it's relative.

    Handles Unix-style absolute paths (starting with '/') on Windows
    by treating them as absolute (for WSL/cross-platform compatibility).
    Also handles Windows drive-letter paths (C:/, D:/) as absolute.
    """
    path_str = str(path)
    # On Windows, Path.is_absolute() returns False for paths starting with '/'
    # Treat Unix-style absolute paths as absolute on all platforms
    # Also treat Windows drive-letter paths (C:/, D:/) as absolute
    is_absolute = (
        path.is_absolute() or
        (os.name == "nt" and path_str.startswith("/")) or
        (os.name == "nt" and len(path_str) >= 2 and path_str[1] == ":" and path_str[2] in ("/", "\\"))
    )
    if is_absolute:
        return path
    return (base / path).resolve()


def discover_obsidian_vaults(search_paths: Optional[List[Path]] = None, max_depth: int = 3) -> List[Path]:
    """
    Discover Obsidian vaults by searching for .obsidian directories.

    Args:
        search_paths: Optional list of paths to search. If None, searches common locations.
        max_depth: Maximum directory depth to search (default 3).

    Returns:
        List of paths containing .obsidian directories, sorted by preference.
    """
    if search_paths is None:
        search_paths = _get_default_vault_search_paths()

    vaults = []
    # Directories to skip during search (common large directories)
    skip_dirs = {'.git', 'node_modules', '__pycache__', '.venv', 'venv', 'env', '.env',
                 'target', 'build', 'dist', '.next', '.nuxt', 'vendor', 'bower_components',
                 'jspm_packages', 'typings', '.sass-cache', '.cache', '.tmp', 'tmp',
                 'logs', 'log', 'backups', 'backup', '.Trash', 'Trash', 'Recycle.Bin'}

    for search_path in search_paths:
        try:
            if not search_path.exists():
                continue
            # Search for .obsidian directories with limited depth
            for obsidian_dir in _rglob_limited(search_path, ".obsidian", max_depth):
                try:
                    if not obsidian_dir.is_dir():
                        continue
                    # Skip if in a skipped directory
                    if any(skip in obsidian_dir.parts for skip in skip_dirs):
                        continue
                    vault_path = obsidian_dir.parent
                    # Verify it's a valid Obsidian vault (has .obsidian folder)
                    if (vault_path / ".obsidian").exists():
                        vaults.append(vault_path.resolve())
                except (PermissionError, OSError):
                    continue
        except (PermissionError, OSError):
            # Skip directories we can't access
            continue

    # Deduplicate while preserving order
    seen = set()
    unique_vaults = []
    for vault in vaults:
        if vault not in seen:
            seen.add(vault)
            unique_vaults.append(vault)

    return unique_vaults


def _rglob_limited(root: Path, pattern: str, max_depth: int) -> List[Path]:
    """
    Recursively glob with depth limit.

    Args:
        root: Root directory to search
        pattern: Glob pattern to match
        max_depth: Maximum depth to search (0 = root only, 1 = root + 1 level, etc.)

    Returns:
        List of matching paths.
    """
    matches = []
    try:
        for item in root.iterdir():
            if item.name == pattern and item.is_dir():
                matches.append(item)
            elif item.is_dir() and max_depth > 0:
                # Skip hidden directories and common skip directories
                if item.name.startswith('.') or item.name in {'.git', 'node_modules', '__pycache__', '.venv', 'venv', 'env', '.env',
                     'target', 'build', 'dist', '.next', '.nuxt', 'vendor', 'bower_components',
                     'jspm_packages', 'typings', '.sass-cache', '.cache', '.tmp', 'tmp',
                     'logs', 'log', 'backups', 'backup', '.Trash', 'Trash', 'Recycle.Bin'}:
                    continue
                matches.extend(_rglob_limited(item, pattern, max_depth - 1))
    except (PermissionError, OSError):
        pass
    return matches


def _get_default_vault_search_paths() -> List[Path]:
    """Get default paths to search for Obsidian vaults."""
    paths = []

    # 1. Current working directory
    paths.append(Path.cwd())

    # 2. User's home directory
    try:
        paths.append(Path.home())
    except Exception:
        pass

    # 3. Common Obsidian vault locations
    home = Path.home()
    common_locations = [
        home / "Documents",
        home / "Obsidian",
        home / "vaults",
        home / "Vaults",
        home / "notes",
        home / "Notes",
        home / "knowledge",
        home / "Knowledge",
        home / "Second Brain",
        home / "second-brain",
    ]
    paths.extend(common_locations)

    # 4. Windows-specific locations
    if os.name == "nt":
        onedrive = os.environ.get("OneDrive")
        if onedrive:
            paths.append(Path(onedrive) / "Documents")
            paths.append(Path(onedrive) / "Obsidian")
        # Check for Documents in common locations
        paths.append(Path("C:/Users") / os.environ.get("USERNAME", "") / "Documents")
        paths.append(Path("D:/Users") / os.environ.get("USERNAME", "") / "Documents")

    # 5. Environment variable override
    if vault_path_env := os.environ.get("OBSIDIAN_VAULT_PATH"):
        paths.append(Path(vault_path_env))

    # Filter out non-existent paths and deduplicate
    seen = set()
    unique_paths = []
    for path in paths:
        try:
            resolved = path.resolve()
            if resolved not in seen and resolved.exists():
                seen.add(resolved)
                unique_paths.append(resolved)
        except Exception:
            continue

    return unique_paths


def discover_vault_interactive(vaults: List[Path]) -> Optional[Path]:
    """
    Prompt user to select a vault when multiple are found.

    Returns:
        Selected vault path, or None if user cancels or no vaults.
    """
    if not vaults:
        return None
    if len(vaults) == 1:
        return vaults[0]

    try:
        import sys
        print("\nMultiple Obsidian vaults found:")
        for i, vault in enumerate(vaults, 1):
            # Count markdown files for display
            try:
                md_count = len(list(vault.rglob("*.md")))
            except Exception:
                md_count = 0
            print(f"  {i}. {vault} ({md_count} .md files)")

        print("  0. Cancel")
        choice = input(f"\nSelect vault [1-{len(vaults)}] or 0 to cancel: ").strip()

        if choice == "0" or not choice:
            return None

        try:
            idx = int(choice) - 1
            if 0 <= idx < len(vaults):
                return vaults[idx]
        except ValueError:
            pass

        print("Invalid selection.")
        return None
    except (EOFError, KeyboardInterrupt):
        return None


def resolve_vault_path(config_vault_path: Optional[Path], project_root: Path) -> Optional[Path]:
    """
    Resolve the vault path using the resolution sequence:
    1. Explicit config/environment variable
    2. Persisted user configuration (from .env)
    3. Automatic discovery
    4. Interactive selection (if multiple found)

    Args:
        config_vault_path: The vault path from config (may be None)
        project_root: Project root for resolving relative paths

    Returns:
        Resolved vault path, or None if no vault found.
    """
    # 1. Explicit config/environment variable (already in config)
    if config_vault_path is not None:
        resolved = resolve_path(config_vault_path, project_root)
        if resolved.exists() and (resolved / ".obsidian").exists():
            logger.info(f"Using explicit vault path: {resolved}")
            return resolved
        else:
            logger.warning(f"Configured vault path does not exist or is not a valid Obsidian vault: {resolved}")

    # 2. Automatic discovery
    logger.info("Searching for Obsidian vaults...")
    vaults = discover_obsidian_vaults()

    if not vaults:
        logger.warning("No Obsidian vaults found automatically")
        return None

    if len(vaults) == 1:
        logger.info(f"Found single vault: {vaults[0]}")
        return vaults[0]

    # Multiple vaults found - try interactive selection
    logger.info(f"Found {len(vaults)} vaults, attempting interactive selection...")
    selected = discover_vault_interactive(vaults)
    if selected:
        logger.info(f"Selected vault: {selected}")
        return selected

    logger.warning("No vault selected")
    return None


def create_config_class(project_root: Path):
    """Create a MemoraConfig class bound to a specific project root.

    This factory creates a new class each time to ensure the env_file
    path is evaluated with the correct project_root.
    """
    env_file_path = str(project_root / ".env")

    class ProjectMemoraConfig(BaseSettings):
        """Main configuration for MEMORA memory infrastructure (project-specific)."""

        model_config = SettingsConfigDict(
            env_file=env_file_path,
            env_file_encoding="utf-8",
            case_sensitive=False,
            extra="ignore",
        )

        # =========================================================================
        # Vault Path (Optional - will be auto-discovered if not provided)
        # =========================================================================
        vault_path: Annotated[Optional[Path], BeforeValidator(_coerce_vault_path)] = Field(
            default=None,
            description="Absolute path to Obsidian vault (folder containing .obsidian/). Auto-discovered if not provided.",
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

        ollama_mode: str = Field(
            default="host",
            description="Ollama deployment mode: 'host' for host Ollama, 'container' for containerized Ollama",
            validation_alias="OLLAMA_MODE",
        )

        ollama_host_fallback: Optional[str] = Field(
            default=None,
            description="Fallback Ollama host for validation (e.g., container endpoint when in host mode)",
            validation_alias="OLLAMA_HOST_FALLBACK",
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

        def validate_ollama_host(self, host: Optional[str] = None) -> bool:
            """
            Validate Ollama host connectivity.

            Args:
                host: Optional host URL to validate. Defaults to self.ollama_host.

            Returns:
                True if Ollama is reachable and model is available.
            """
            import httpx

            target_host = host or self.ollama_host
            try:
                response = httpx.get(f"{target_host}/api/tags", timeout=5.0)
                if response.status_code != 200:
                    logger.warning(f"Ollama health check failed for {target_host}: {response.status_code}")
                    return False
                models = response.json().get("models", [])
                model_available = any(m.get("name", "").startswith(self.embedding_model) for m in models)
                if not model_available:
                    logger.warning(f"Model '{self.embedding_model}' not found on {target_host}")
                return model_available
            except Exception as e:
                logger.warning(f"Ollama validation error for {target_host}: {e}")
                return False

        def validate_ollama_both_modes(self) -> dict:
            """
            Validate both host and container Ollama endpoints.

            Returns:
                Dict with validation results for each mode.
            """
            results = {
                "host": {"configured": self.ollama_mode == "host", "valid": False},
                "container": {"configured": self.ollama_mode == "container", "valid": False},
            }

            # Validate primary mode
            if self.ollama_mode == "host":
                results["host"]["valid"] = self.validate_ollama_host()
                # Also validate fallback if configured
                if self.ollama_host_fallback:
                    results["container"]["valid"] = self.validate_ollama_host(self.ollama_host_fallback)
            else:  # container mode
                results["container"]["valid"] = self.validate_ollama_host()
                # Also validate fallback if configured
                if self.ollama_host_fallback:
                    results["host"]["valid"] = self.validate_ollama_host(self.ollama_host_fallback)

            return results

        @model_validator(mode="after")
        def resolve_paths(self) -> "ProjectMemoraConfig":
            """Resolve all relative paths against project root after settings are loaded."""
            # Resolve storage paths
            self.chroma_path = resolve_path(self.chroma_path, project_root)
            self.sqlite_path = resolve_path(self.sqlite_path, project_root)
            if self.log_file:
                self.log_file = resolve_path(self.log_file, project_root)
            # Resolve vault path using automatic discovery if not explicitly set
            self.vault_path = resolve_vault_path(self.vault_path, project_root)
            return self

    return ProjectMemoraConfig


# Global config instance (for backward compatibility with default project root)
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
    """Load configuration from a specific project root.

    Creates a new config class bound to the given project root,
    ensuring complete isolation between different projects.

    Args:
        project_root: Path to the project root containing .env file

    Returns:
        A new MemoraConfig instance bound to the project root
    """
    config_class = create_config_class(project_root)
    return config_class()


# Export for backward compatibility
MemoraConfig = _MemoraConfig
PROJECT_ROOT = _DEFAULT_PROJECT_ROOT