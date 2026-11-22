"""
MEMORA System Diagnostics

Comprehensive health checks for all MEMORA components.
Implements `memora doctor` command for system validation.
"""

import os
import sys
import shutil
import sqlite3
import platform
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from enum import Enum

# Import mcp at module level for test patching
try:
    import mcp
except ImportError:
    mcp = None

from memora.config import get_config, MemoraConfig, resolve_vault_path, discover_obsidian_vaults
from memora.storage.metadata_store import MetadataStore
from memora.storage.vector_store import VectorStore
from memora.embeddings.ollama_provider import OllamaProvider
from memora.ingestion.vault_reader import VaultReader


class CheckStatus(Enum):
    """Health check status levels."""
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"
    SKIP = "SKIP"


def _check_python_version(version_info: tuple, version_str: str) -> tuple[CheckStatus, str, dict]:
    """
    Check Python version compatibility.

    Args:
        version_info: sys.version_info tuple
        version_str: Version string

    Returns:
        Tuple of (status, message, details)
    """
    if version_info >= (3, 10):
        return (CheckStatus.PASS,
                f"Python {version_str} (supported)",
                {"version": version_str})
    elif version_info >= (3, 9):
        return (CheckStatus.WARN,
                f"Python {version_str} (minimum 3.10 recommended)",
                {"version": version_str})
    else:
        return (CheckStatus.FAIL,
                f"Python {version_str} (requires 3.10+)",
                {"version": version_str})


@dataclass
class CheckResult:
    """Result of a single health check."""
    name: str
    status: CheckStatus
    message: str = ""
    details: Dict[str, Any] = field(default_factory=dict)
    remediation: Optional[str] = None


@dataclass
class DoctorReport:
    """Complete diagnostic report."""
    checks: List[CheckResult] = field(default_factory=list)
    python_version: str = ""
    platform: str = ""
    config_path: str = ""

    @property
    def overall_status(self) -> CheckStatus:
        """Determine overall system status."""
        if any(c.status == CheckStatus.FAIL for c in self.checks):
            return CheckStatus.FAIL
        if any(c.status == CheckStatus.WARN for c in self.checks):
            return CheckStatus.WARN
        return CheckStatus.PASS

    @property
    def exit_code(self) -> int:
        """Exit code for the doctor command."""
        if self.overall_status == CheckStatus.FAIL:
            return 1
        if self.overall_status == CheckStatus.WARN:
            return 2
        return 0

    def add_check(self, result: CheckResult) -> None:
        """Add a check result."""
        self.checks.append(result)

    def get_summary(self) -> Dict[str, int]:
        """Get count of each status."""
        counts = {s: 0 for s in CheckStatus}
        for c in self.checks:
            counts[c.status] += 1
        return counts


class Doctor:
    """
    MEMORA System Diagnostics.

    Performs comprehensive health checks across all components:
    - Python environment
    - Configuration
    - Ollama connectivity and model
    - ChromaDB accessibility
    - SQLite integrity
    - Obsidian vault validity
    - Embedding pipeline
    - MCP server configuration
    - Storage permissions and disk space
    """

    def __init__(self, config: Optional[MemoraConfig] = None, verbose: bool = False):
        self.config = config
        self.verbose = verbose
        self.config_error: Optional[str] = None

        # Try to load config, but don't fail if it's invalid
        if self.config is None:
            try:
                from memora.config import get_config
                self.config = get_config()
            except Exception as e:
                self.config_error = str(e)
                self.config = None

        config_path = "unknown"
        if self.config and self.config.vault_path:
            config_path = str(self.config.vault_path)
        elif self.config_error:
            config_path = f"error: {self.config_error}"

        self.report = DoctorReport(
            python_version=platform.python_version(),
            platform=platform.platform(),
            config_path=config_path
        )

    def run_all(self) -> DoctorReport:
        """Run all diagnostic checks."""
        # Core environment
        self._check_python_environment()
        self._check_dependencies()

        # Configuration
        self._check_configuration()

        # External services
        self._check_ollama()
        self._check_embedding_model()
        self._check_chromadb()
        self._check_sqlite()

        # Vault
        self._check_obsidian_vault()

        # Pipeline
        self._check_embedding_pipeline()

        # MCP
        self._check_mcp_configuration()

        # Storage
        self._check_storage()

        return self.report

    def _check_python_environment(self) -> None:
        """Check Python version compatibility."""
        version_info = sys.version_info
        version_str = f"{version_info.major}.{version_info.minor}.{version_info.micro}"

        status, message, details = _check_python_version(version_info, version_str)
        details["executable"] = sys.executable

        remediation = None
        if status == CheckStatus.WARN:
            remediation = "Upgrade to Python 3.10+ for best compatibility"
        elif status == CheckStatus.FAIL:
            remediation = "Install Python 3.10 or higher"

        self.report.add_check(CheckResult(
            name="Python Environment",
            status=status,
            message=message,
            details=details,
            remediation=remediation
        ))

    def _check_dependencies(self) -> None:
        """Check critical Python dependencies."""
        required = [
            ("pydantic", "pydantic"),
            ("pydantic_settings", "pydantic_settings"),
            ("chromadb", "chromadb"),
            ("ollama", "ollama"),
            ("mcp", "mcp"),
            ("httpx", "httpx"),
            ("typer", "typer"),
            ("rich", "rich"),
            ("yaml", "PyYAML"),
            ("frontmatter", "python-frontmatter"),
            ("watchdog", "watchdog"),
            ("pathspec", "pathspec"),
        ]

        missing = []
        for import_name, pkg_name in required:
            try:
                __import__(import_name)
            except ImportError:
                missing.append(pkg_name)

        if not missing:
            self.report.add_check(CheckResult(
                name="Dependencies",
                status=CheckStatus.PASS,
                message="All required packages installed",
                details={"checked": len(required)}
            ))
        else:
            self.report.add_check(CheckResult(
                name="Dependencies",
                status=CheckStatus.FAIL,
                message=f"Missing packages: {', '.join(missing)}",
                details={"missing": missing, "total_checked": len(required)},
                remediation=f"Run: pip install {' '.join(missing)}"
            ))

    def _check_configuration(self) -> None:
        """Check configuration validity."""
        if self.config_error:
            self.report.add_check(CheckResult(
                name="Configuration",
                status=CheckStatus.FAIL,
                message=f"Configuration load failed: {self.config_error}",
                details={"error": self.config_error},
                remediation="Set VAULT_PATH in .env or ensure an Obsidian vault is discoverable"
            ))
            return

        if not self.config:
            self.report.add_check(CheckResult(
                name="Configuration",
                status=CheckStatus.FAIL,
                message="Configuration not available",
                remediation="Fix configuration loading"
            ))
            return

        issues = []
        warnings = []

        # Check vault path
        if not self.config.vault_path:
            issues.append("VAULT_PATH not configured and no vault auto-discovered")
        else:
            vault_str = str(self.config.vault_path).strip()
            if vault_str == "" or vault_str == ".":
                issues.append("VAULT_PATH not configured (empty or current directory)")
            elif not self.config.vault_path.exists():
                issues.append(f"VAULT_PATH does not exist: {self.config.vault_path}")

        # Check paths are resolved
        if self.config:
            if not self.config.chroma_path.is_absolute():
                warnings.append(f"CHROMA_PATH is relative: {self.config.chroma_path}")
            if not self.config.sqlite_path.is_absolute():
                warnings.append(f"SQLITE_PATH is relative: {self.config.sqlite_path}")

            # Check embedding dimensions match common models
            model_dims = {
                "nomic-embed-text": 768,
                "mxbai-embed-large": 1024,
                "all-minilm": 384,
                "bge-m3": 1024,
                "bge-base": 768,
                "bge-large": 1024,
            }
            expected_dims = model_dims.get(self.config.embedding_model)
            if expected_dims and self.config.embedding_dimensions != expected_dims:
                warnings.append(
                    f"EMBEDDING_DIMENSIONS ({self.config.embedding_dimensions}) "
                    f"may not match {self.config.embedding_model} ({expected_dims})"
                )

        if issues:
            self.report.add_check(CheckResult(
                name="Configuration",
                status=CheckStatus.FAIL,
                message="; ".join(issues),
                details={"issues": issues, "warnings": warnings},
                remediation="Set VAULT_PATH in .env or ensure an Obsidian vault is discoverable"
            ))
        elif warnings:
            self.report.add_check(CheckResult(
                name="Configuration",
                status=CheckStatus.WARN,
                message="Configuration valid with warnings: " + "; ".join(warnings),
                details={"warnings": warnings},
                remediation="Review warnings above"
            ))
        else:
            self.report.add_check(CheckResult(
                name="Configuration",
                status=CheckStatus.PASS,
                message="Configuration valid",
                details={
                    "vault_path": str(self.config.vault_path) if self.config and self.config.vault_path else "auto-discovered",
                    "chroma_path": str(self.config.chroma_path) if self.config else "unknown",
                    "sqlite_path": str(self.config.sqlite_path) if self.config else "unknown",
                    "embedding_model": self.config.embedding_model if self.config else "unknown",
                    "embedding_dimensions": self.config.embedding_dimensions if self.config else 0,
                }
            ))

    def _create_ollama_provider(self):
        """Create Ollama provider (overridable for testing)."""
        if not self.config:
            return None
        return OllamaProvider(
            host=self.config.ollama_host,
            model=self.config.embedding_model
        )

    def _check_ollama(self) -> None:
        """Check Ollama server connectivity."""
        if not self.config:
            self.report.add_check(CheckResult(
                name="Ollama Connectivity",
                status=CheckStatus.FAIL,
                message="Configuration not available",
                remediation="Fix configuration first"
            ))
            return

        try:
            provider = self._create_ollama_provider()
            if not provider:
                self.report.add_check(CheckResult(
                    name="Ollama Connectivity",
                    status=CheckStatus.FAIL,
                    message="Could not create Ollama provider",
                    remediation="Fix configuration first"
                ))
                return

            healthy = provider.health_check()
            if healthy:
                self.report.add_check(CheckResult(
                    name="Ollama Connectivity",
                    status=CheckStatus.PASS,
                    message=f"Connected to {self.config.ollama_host}",
                    details={"host": self.config.ollama_host}
                ))
            else:
                self.report.add_check(CheckResult(
                    name="Ollama Connectivity",
                    status=CheckStatus.FAIL,
                    message=f"Cannot connect to Ollama at {self.config.ollama_host}",
                    details={"host": self.config.ollama_host},
                    remediation="Start Ollama: 'ollama serve' or check OLLAMA_HOST in .env"
                ))
        except Exception as e:
            self.report.add_check(CheckResult(
                name="Ollama Connectivity",
                status=CheckStatus.FAIL,
                message=f"Ollama connection error: {e}",
                details={"host": self.config.ollama_host, "error": str(e)},
                remediation="Ensure Ollama is running and accessible"
            ))

    def _check_embedding_model(self) -> None:
        """Check required embedding model is available."""
        if not self.config:
            self.report.add_check(CheckResult(
                name="Embedding Model",
                status=CheckStatus.FAIL,
                message="Configuration not available",
                remediation="Fix configuration first"
            ))
            return

        try:
            provider = self._create_ollama_provider()
            if not provider:
                self.report.add_check(CheckResult(
                    name="Embedding Model",
                    status=CheckStatus.FAIL,
                    message="Could not create Ollama provider",
                    remediation="Fix configuration first"
                ))
                return

            model_info = provider.get_model_info()
            model_name = model_info.get("name", self.config.embedding_model)

            # Check if model exists in available models
            import httpx
            response = httpx.get(f"{self.config.ollama_host}/api/tags", timeout=5.0)
            models = response.json().get("models", [])
            model_names = [m.get("name", "") for m in models]

            available = any(
                self.config.embedding_model in m
                for m in model_names
            )

            if available:
                dims = model_info.get("dimensions", self.config.embedding_dimensions)
                self.report.add_check(CheckResult(
                    name="Embedding Model",
                    status=CheckStatus.PASS,
                    message=f"Model '{self.config.embedding_model}' available ({dims}d)",
                    details={"model": model_name, "dimensions": dims, "available_models": model_names}
                ))
            else:
                self.report.add_check(CheckResult(
                    name="Embedding Model",
                    status=CheckStatus.FAIL,
                    message=f"Model '{self.config.embedding_model}' not found in Ollama",
                    details={"configured": self.config.embedding_model, "available": model_names},
                    remediation=f"Run: ollama pull {self.config.embedding_model}"
                ))
        except Exception as e:
            self.report.add_check(CheckResult(
                name="Embedding Model",
                status=CheckStatus.FAIL,
                message=f"Failed to verify model: {e}",
                details={"error": str(e)},
                remediation="Check Ollama is running and model name is correct"
            ))

    def _check_chromadb(self) -> None:
        """Check ChromaDB accessibility and collection."""
        if not self.config:
            self.report.add_check(CheckResult(
                name="ChromaDB",
                status=CheckStatus.FAIL,
                message="Configuration not available",
                remediation="Fix configuration first"
            ))
            return

        try:
            vector_store = VectorStore(persist_path=str(self.config.chroma_path))
            info = vector_store.get_collection_info()
            count = info.get("count", 0)
            metadata = info.get("metadata", {})

            # Verify collection metadata matches config
            stored_model = metadata.get("embedding_model", "unknown")
            stored_dims = metadata.get("embedding_dimensions", "unknown")

            warnings = []
            if stored_model != self.config.embedding_model:
                warnings.append(f"Collection model '{stored_model}' != config '{self.config.embedding_model}'")
            if str(stored_dims) != str(self.config.embedding_dimensions):
                warnings.append(f"Collection dims '{stored_dims}' != config '{self.config.embedding_dimensions}'")

            if warnings:
                self.report.add_check(CheckResult(
                    name="ChromaDB",
                    status=CheckStatus.WARN,
                    message=f"Connected ({count} vectors) with metadata mismatches",
                    details={"count": count, "metadata": metadata, "warnings": warnings},
                    remediation="Consider full re-index if model changed: memora ingest --full"
                ))
            else:
                self.report.add_check(CheckResult(
                    name="ChromaDB",
                    status=CheckStatus.PASS,
                    message=f"Connected ({count} vectors)",
                    details={"count": count, "metadata": metadata}
                ))

        except Exception as e:
            self.report.add_check(CheckResult(
                name="ChromaDB",
                status=CheckStatus.FAIL,
                message=f"ChromaDB connection failed: {e}",
                details={"path": str(self.config.chroma_path), "error": str(e)},
                remediation="Check CHROMA_PATH permissions and disk space"
            ))

    def _check_sqlite(self) -> None:
        """Check SQLite database accessibility and integrity."""
        if not self.config:
            self.report.add_check(CheckResult(
                name="SQLite",
                status=CheckStatus.FAIL,
                message="Configuration not available",
                remediation="Fix configuration first"
            ))
            return

        try:
            metadata_store = MetadataStore(db_path=self.config.sqlite_path)

            # Test basic connectivity
            stats = metadata_store.get_index_stats()

            # Test integrity with PRAGMA
            with sqlite3.connect(self.config.sqlite_path) as conn:
                conn.execute("PRAGMA integrity_check")

            # Check for WAL mode (better concurrency)
            with sqlite3.connect(self.config.sqlite_path) as conn:
                journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]

            warnings = []
            if journal_mode.upper() != "WAL":
                warnings.append(f"Journal mode is {journal_mode} (WAL recommended for concurrency)")

            if warnings:
                self.report.add_check(CheckResult(
                    name="SQLite",
                    status=CheckStatus.WARN,
                    message=f"Database accessible ({stats.get('total_chunks', 0)} chunks): {'; '.join(warnings)}",
                    details={"stats": stats, "journal_mode": journal_mode, "warnings": warnings},
                    remediation="Consider enabling WAL mode for better concurrency"
                ))
            else:
                self.report.add_check(CheckResult(
                    name="SQLite",
                    status=CheckStatus.PASS,
                    message=f"Database healthy ({stats.get('total_chunks', 0)} chunks, WAL mode)",
                    details={"stats": stats, "journal_mode": journal_mode}
                ))

        except sqlite3.DatabaseError as e:
            self.report.add_check(CheckResult(
                name="SQLite",
                status=CheckStatus.FAIL,
                message=f"Database integrity error: {e}",
                details={"path": str(self.config.sqlite_path), "error": str(e)},
                remediation="Database may be corrupted. Backup and re-index: memora ingest --full"
            ))
        except Exception as e:
            self.report.add_check(CheckResult(
                name="SQLite",
                status=CheckStatus.FAIL,
                message=f"SQLite connection failed: {e}",
                details={"path": str(self.config.sqlite_path), "error": str(e)},
                remediation="Check SQLITE_PATH permissions and disk space"
            ))

    def _check_obsidian_vault(self) -> None:
        """Check Obsidian vault validity and accessibility."""
        if not self.config:
            self.report.add_check(CheckResult(
                name="Obsidian Vault",
                status=CheckStatus.FAIL,
                message="Configuration not available",
                remediation="Fix configuration first"
            ))
            return

        try:
            vault_path = self.config.vault_path

            if not vault_path:
                self.report.add_check(CheckResult(
                    name="Obsidian Vault",
                    status=CheckStatus.FAIL,
                    message="No vault path configured and no vault auto-discovered",
                    remediation="Set VAULT_PATH in .env or ensure an Obsidian vault is discoverable"
                ))
                return

            # Check .obsidian directory
            obsidian_dir = vault_path / ".obsidian"
            if not obsidian_dir.exists():
                self.report.add_check(CheckResult(
                    name="Obsidian Vault",
                    status=CheckStatus.FAIL,
                    message=f"No .obsidian directory at {vault_path}",
                    details={"vault_path": str(vault_path)},
                    remediation="Ensure VAULT_PATH points to Obsidian vault root (containing .obsidian/)"
                ))
                return

            # Check read permissions
            test_file = vault_path / ".memora_read_test"
            try:
                test_file.write_text("test")
                test_file.unlink()
                can_write = True
            except Exception:
                can_write = False

            # Count markdown files
            vault_reader = VaultReader(vault_path=vault_path)
            md_files = vault_reader.list_files([".md"])

            # Check for common issues
            warnings = []
            if len(md_files) == 0:
                warnings.append("No .md files found in vault")
            if not can_write:
                warnings.append("Vault directory not writable (read-only is OK for indexing)")

            # Check for config files that might indicate issues
            if (obsidian_dir / "workspace").exists():
                pass  # Normal
            if (obsidian_dir / "workspace-mobile").exists():
                pass  # Normal

            if warnings:
                self.report.add_check(CheckResult(
                    name="Obsidian Vault",
                    status=CheckStatus.WARN,
                    message=f"Vault accessible ({len(md_files)} .md files): {'; '.join(warnings)}",
                    details={"vault_path": str(vault_path), "file_count": len(md_files), "writable": can_write, "warnings": warnings},
                    remediation="Review warnings above"
                ))
            else:
                self.report.add_check(CheckResult(
                    name="Obsidian Vault",
                    status=CheckStatus.PASS,
                    message=f"Vault valid ({len(md_files)} .md files)",
                    details={"vault_path": str(vault_path), "file_count": len(md_files), "writable": can_write}
                ))

        except Exception as e:
            self.report.add_check(CheckResult(
                name="Obsidian Vault",
                status=CheckStatus.FAIL,
                message=f"Vault check failed: {e}",
                details={"vault_path": str(self.config.vault_path) if self.config.vault_path else "none", "error": str(e)},
                remediation="Check VAULT_PATH in .env and permissions"
            ))

    def _check_embedding_pipeline(self) -> None:
        """Check embedding generation pipeline end-to-end."""
        if not self.config:
            self.report.add_check(CheckResult(
                name="Embedding Pipeline",
                status=CheckStatus.FAIL,
                message="Configuration not available",
                remediation="Fix configuration first"
            ))
            return

        try:
            provider = self._create_ollama_provider()
            if not provider:
                self.report.add_check(CheckResult(
                    name="Embedding Pipeline",
                    status=CheckStatus.FAIL,
                    message="Could not create Ollama provider",
                    remediation="Fix configuration first"
                ))
                return

            # Test embedding generation
            result = provider.generate_embeddings(["test embedding pipeline"])

            if result.embeddings and len(result.embeddings) == 1:
                emb = result.embeddings[0]
                actual_dims = len(emb)

                if actual_dims == self.config.embedding_dimensions:
                    self.report.add_check(CheckResult(
                        name="Embedding Pipeline",
                        status=CheckStatus.PASS,
                        message=f"Generated {actual_dims}d embedding successfully",
                        details={"dimensions": actual_dims, "model": result.model, "tokens": result.token_count}
                    ))
                else:
                    self.report.add_check(CheckResult(
                        name="Embedding Pipeline",
                        status=CheckStatus.WARN,
                        message=f"Embedding dimensions mismatch: got {actual_dims}, expected {self.config.embedding_dimensions}",
                        details={"actual": actual_dims, "expected": self.config.embedding_dimensions, "model": result.model},
                        remediation="Update EMBEDDING_DIMENSIONS in .env to match model output"
                    ))
            else:
                self.report.add_check(CheckResult(
                    name="Embedding Pipeline",
                    status=CheckStatus.FAIL,
                    message="Failed to generate test embedding",
                    details={"result": str(result)},
                    remediation="Check Ollama model and embedding endpoint"
                ))

        except Exception as e:
            self.report.add_check(CheckResult(
                name="Embedding Pipeline",
                status=CheckStatus.FAIL,
                message=f"Embedding pipeline error: {e}",
                details={"error": str(e)},
                remediation="Verify Ollama is running and model is loaded"
            ))

    def _check_mcp_configuration(self) -> None:
        """Check MCP server configuration."""
        if not self.config:
            self.report.add_check(CheckResult(
                name="MCP Configuration",
                status=CheckStatus.FAIL,
                message="Configuration not available",
                remediation="Fix configuration first"
            ))
            return

        # Check if mcp module is importable and version is compatible
        if mcp is None:
            self.report.add_check(CheckResult(
                name="MCP Configuration",
                status=CheckStatus.FAIL,
                message="MCP package not installed",
                details={},
                remediation="Install: pip install mcp>=1.0.0"
            ))
            return

        mcp_version = getattr(mcp, "__version__", "unknown")

        # Check transport config
        transport = self.config.mcp_transport
        valid_transports = ["stdio", "http", "sse", "streamable-http"]
        if transport not in valid_transports:
            self.report.add_check(CheckResult(
                name="MCP Configuration",
                status=CheckStatus.WARN,
                message=f"Unknown MCP transport: {transport}",
                details={"transport": transport, "valid": valid_transports},
                remediation=f"Use one of: {', '.join(valid_transports)}"
            ))
            return

        self.report.add_check(CheckResult(
            name="MCP Configuration",
            status=CheckStatus.PASS,
            message=f"MCP {mcp_version} configured for {transport} transport",
            details={"version": mcp_version, "transport": transport, "host": self.config.mcp_host, "port": self.config.mcp_port}
        ))

    def _check_storage(self) -> None:
        """Check storage directories and disk space."""
        if not self.config:
            self.report.add_check(CheckResult(
                name="Storage",
                status=CheckStatus.FAIL,
                message="Configuration not available",
                remediation="Fix configuration first"
            ))
            return

        try:
            # Check data directories exist
            paths_to_check = [
                ("Data directory", self.config.data_dir),
                ("ChromaDB path", self.config.chroma_path),
                ("SQLite path", self.config.sqlite_path.parent),
            ]

            issues = []
            warnings = []

            for name, path in paths_to_check:
                if not path.exists():
                    try:
                        path.mkdir(parents=True, exist_ok=True)
                        warnings.append(f"Created missing directory: {path}")
                    except Exception as e:
                        issues.append(f"Cannot create {name}: {path} ({e})")

                # Check write permissions
                test_file = path / ".memora_write_test"
                try:
                    test_file.write_text("test")
                    test_file.unlink()
                except Exception:
                    warnings.append(f"{name} not writable: {path}")

            # Check disk space (warn if < 1GB free)
            try:
                usage = shutil.disk_usage(self.config.data_dir)
                free_gb = usage.free / (1024**3)
                if free_gb < 1:
                    warnings.append(f"Low disk space: {free_gb:.1f}GB free")
                elif free_gb < 5:
                    warnings.append(f"Disk space moderate: {free_gb:.1f}GB free")
            except Exception:
                pass

            if issues:
                self.report.add_check(CheckResult(
                    name="Storage",
                    status=CheckStatus.FAIL,
                    message="; ".join(issues),
                    details={"issues": issues, "warnings": warnings},
                    remediation="Fix directory permissions and ensure disk space"
                ))
            elif warnings:
                self.report.add_check(CheckResult(
                    name="Storage",
                    status=CheckStatus.WARN,
                    message="Storage accessible with warnings: " + "; ".join(warnings),
                    details={"warnings": warnings},
                    remediation="Review warnings above"
                ))
            else:
                self.report.add_check(CheckResult(
                    name="Storage",
                    status=CheckStatus.PASS,
                    message="Storage directories accessible with sufficient space",
                    details={
                        "data_dir": str(self.config.data_dir),
                        "chroma_path": str(self.config.chroma_path),
                        "sqlite_path": str(self.config.sqlite_path),
                    }
                ))

        except Exception as e:
            self.report.add_check(CheckResult(
                name="Storage",
                status=CheckStatus.FAIL,
                message=f"Storage check failed: {e}",
                details={"error": str(e)},
                remediation="Check paths and permissions"
            ))


def run_doctor(config: Optional[MemoraConfig] = None, verbose: bool = False, json_output: bool = False) -> DoctorReport:
    """Run diagnostics and return report."""
    doctor = Doctor(config=config, verbose=verbose)
    report = doctor.run_all()

    if json_output:
        import json
        output = {
            "status": report.overall_status.value,
            "exit_code": report.exit_code,
            "python_version": report.python_version,
            "platform": report.platform,
            "checks": [
                {
                    "name": c.name,
                    "status": c.status.value,
                    "message": c.message,
                    "details": c.details,
                    "remediation": c.remediation
                }
                for c in report.checks
            ]
        }
        print(json.dumps(output, indent=2))
    else:
        _print_report(report)

    return report


def _print_report(report: DoctorReport) -> None:
    """Print formatted diagnostic report."""
    print("=" * 40)
    print("     MEMORA SYSTEM DIAGNOSTICS")
    print("=" * 40)
    print()

    status_symbols = {
        CheckStatus.PASS: "[PASS]",
        CheckStatus.WARN: "[WARN]",
        CheckStatus.FAIL: "[FAIL]",
        CheckStatus.SKIP: "[SKIP]",
    }

    for check in report.checks:
        symbol = status_symbols.get(check.status, "[?]")
        print(f"{symbol} {check.name}")
        if check.message:
            print(f"      {check.message}")
        if check.remediation and check.status in (CheckStatus.WARN, CheckStatus.FAIL):
            print(f"      -> {check.remediation}")

    print()
    print("=" * 40)

    summary = report.get_summary()
    status_str = report.overall_status.value
    print(f"STATUS: {status_str}")
    print(f"  PASS: {summary[CheckStatus.PASS]}  WARN: {summary[CheckStatus.WARN]}  FAIL: {summary[CheckStatus.FAIL]}  SKIP: {summary[CheckStatus.SKIP]}")
    print("=" * 40)