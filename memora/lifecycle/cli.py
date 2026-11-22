"""
MEMORA Lifecycle Manager CLI

Unified command-line interface for managing MEMORA deployment.
Commands: start, stop, restart, status, doctor, logs, version
"""

import os
import sys
import json
import subprocess
import shutil
import platform
import socket
import time
from pathlib import Path
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field
from enum import Enum

import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.text import Text

from memora.config import get_config, MemoraConfig, find_project_root, PROJECT_ROOT
from memora.diagnostics import run_doctor, DoctorReport, CheckStatus
from memora.lifecycle.dependency_manager import (
    DependencyLifecycleManager,
    StartupConfig,
    DependencyType,
)

# Initialize Typer app
app = typer.Typer(
    name="memora",
    help="MEMORA — Local-First Persistent Memory Infrastructure for AI",
    add_completion=False,
    no_args_is_help=True,
)
console = Console()


# =========================================================================
# Data Classes
# =========================================================================

class ValidationSeverity(Enum):
    """Severity levels for validation checks."""
    INFO = "INFO"
    WARN = "WARN"
    ERROR = "ERROR"


@dataclass
class ValidationResult:
    """Result of a single validation check."""
    name: str
    severity: ValidationSeverity
    message: str
    details: Dict[str, Any] = field(default_factory=dict)
    remediation: Optional[str] = None


@dataclass
class PreflightReport:
    """Complete preflight validation report."""
    results: List[ValidationResult] = field(default_factory=list)
    project_root: Path = Path()
    config: Optional[MemoraConfig] = None

    @property
    def has_errors(self) -> bool:
        return any(r.severity == ValidationSeverity.ERROR for r in self.results)

    @property
    def has_warnings(self) -> bool:
        return any(r.severity == ValidationSeverity.WARN for r in self.results)

    def add_result(self, result: ValidationResult) -> None:
        self.results.append(result)

    def get_summary(self) -> Dict[str, int]:
        counts = {"ERROR": 0, "WARN": 0, "INFO": 0}
        for r in self.results:
            counts[r.severity.value] += 1
        return counts


@dataclass
class ContainerStatus:
    """Status of a Docker container."""
    name: str
    status: str  # running, exited, created, etc.
    health: Optional[str] = None
    ports: List[str] = field(default_factory=list)
    image: str = ""


# =========================================================================
# Startup Locking
# =========================================================================

class StartupLock:
    """Process-safe startup lock using file-based locking.

    Prevents concurrent startup requests from launching duplicate instances.
    Uses platform-appropriate locking (fcntl on Unix, file locking on Windows).
    """

    def __init__(self, project_root: Path, lock_name: str = "memora-startup.lock"):
        self.lock_path = project_root / lock_name
        self.lock_file: Optional[Any] = None
        self._acquired = False

    def acquire(self, timeout: float = 10.0, poll_interval: float = 0.1) -> bool:
        """Acquire the startup lock.

        Args:
            timeout: Maximum time to wait for lock (seconds)
            poll_interval: Time between lock attempts (seconds)

        Returns:
            True if lock acquired, False if timeout
        """
        start_time = time.time()

        while time.time() - start_time < timeout:
            try:
                # Open lock file (create if doesn't exist)
                self.lock_file = open(self.lock_path, "w")

                if platform.system() == "Windows":
                    # Windows: use msvcrt.locking or try-except on file access
                    try:
                        import msvcrt
                        msvcrt.locking(self.lock_file.fileno(), msvcrt.LK_NBLCK, 1)
                    except (ImportError, OSError):
                        # Fallback: try to write PID and check if we're the owner
                        self.lock_file.write(str(os.getpid()))
                        self.lock_file.flush()
                else:
                    # Unix: use fcntl for advisory locking
                    import fcntl
                    fcntl.flock(self.lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

                # Write our PID for debugging
                self.lock_file.seek(0)
                self.lock_file.write(str(os.getpid()))
                self.lock_file.truncate()
                self.lock_file.flush()

                self._acquired = True
                return True

            except (OSError, IOError) as e:
                if self.lock_file:
                    try:
                        self.lock_file.close()
                    except Exception:
                        pass
                    self.lock_file = None

                # Check if it's a locking error (expected) vs other error
                import errno
                if isinstance(e, OSError) and e.errno in (errno.EACCES, errno.EAGAIN, errno.EWOULDBLOCK):
                    pass  # Lock held by another process
                else:
                    # Other error - log and retry
                    pass

            # Wait before retry
            time.sleep(poll_interval)

        return False

    def release(self) -> None:
        """Release the startup lock."""
        if self._acquired and self.lock_file:
            try:
                if platform.system() == "Windows":
                    try:
                        import msvcrt
                        msvcrt.locking(self.lock_file.fileno(), msvcrt.LK_UNLCK, 1)
                    except (ImportError, OSError):
                        pass
                else:
                    import fcntl
                    fcntl.flock(self.lock_file.fileno(), fcntl.LOCK_UN)

                self.lock_file.close()
            except Exception:
                pass
            finally:
                self.lock_file = None
                self._acquired = False

                # Try to remove lock file
                try:
                    self.lock_path.unlink(missing_ok=True)
                except Exception:
                    pass

    def __enter__(self):
        if self.acquire():
            return self
        raise RuntimeError("Could not acquire startup lock")

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()
        return False

    @property
    def is_acquired(self) -> bool:
        return self._acquired


# =========================================================================
# Project Root Discovery
# =========================================================================

def discover_project_root() -> Path:
    """
    Discover MEMORA project root.

    Priority:
    1. MEMORA_HOME environment variable (if set and valid)
    2. Installed MEMORA deployment directory (contains .venv/ or scripts/ - indicates installed deployment)
    3. Current working directory (if contains docker-compose.yml AND no .venv - indicates source project)
    4. Current working directory (if contains pyproject.toml or .env)
    5. Parent of memora package (fallback)
    """
    # 1. Check MEMORA_HOME
    memora_home = os.environ.get("MEMORA_HOME")
    if memora_home:
        path = Path(memora_home).expanduser().resolve()
        if (path / "pyproject.toml").exists() or (path / ".env").exists() or (path / "docker-compose.yml").exists():
            return path
        console.print(f"[yellow]Warning:[/yellow] MEMORA_HOME set but invalid: {memora_home}")

    # 2. Check for installed MEMORA deployment (has .venv or scripts dir)
    cwd = Path.cwd()
    if (cwd / ".venv").exists() or (cwd / "scripts").exists():
        # This is likely an installed deployment directory
        return cwd

    # 3. Check current working directory for source project (docker-compose.yml but no .venv)
    if (cwd / "docker-compose.yml").exists() and not (cwd / ".venv").exists():
        return cwd

    # 4. Check current working directory for pyproject.toml or .env
    if (cwd / "pyproject.toml").exists() or (cwd / ".env").exists():
        return cwd

    # 5. Fallback to package location
    return find_project_root()


def load_config(project_root: Path) -> MemoraConfig:
    """Load configuration from project root.

    Uses the factory function from memora.config which creates
    a project-specific config class, ensuring complete isolation.
    """
    from memora.config import load_config as config_load
    return config_load(project_root)


# =========================================================================
# Preflight Validation Engine
# =========================================================================

class PreflightValidator:
    """Comprehensive preflight validation for MEMORA startup."""

    def __init__(self, project_root: Path, config: MemoraConfig):
        self.project_root = project_root
        self.config = config
        self.report = PreflightReport(project_root=project_root, config=config)

    def run_all(self) -> PreflightReport:
        """Run all preflight validation checks."""
        console.print("[bold]Running preflight validation...[/bold]\n")

        # A. System Requirements
        self._check_os_compatibility()
        self._check_python_version()
        self._check_docker_cli()
        self._check_docker_daemon()
        self._check_docker_compose()
        self._check_permissions()

        # B. Configuration Validation
        self._check_compose_files()
        self._check_dockerfile()
        self._check_env_files()
        self._check_required_env_vars()
        self._check_ollama_mode()
        self._check_vault_path()
        self._validate_docker_bind_mount()
        self._check_volume_config()
        self._check_compose_config()

        # C. Ollama Validation
        self._check_ollama_connectivity()

        # D. Networking Validation
        self._check_port_availability()
        self._check_existing_containers()

        # E. Storage Validation
        self._check_storage_directories()
        self._check_volume_mounts()

        return self.report

    def _add_result(self, name: str, severity: ValidationSeverity, message: str,
                    details: Dict = None, remediation: str = None) -> None:
        self.report.add_result(ValidationResult(
            name=name,
            severity=severity,
            message=message,
            details=details or {},
            remediation=remediation
        ))

    # --- A. System Requirements ---

    def _check_os_compatibility(self) -> None:
        """Check operating system compatibility."""
        system = platform.system()
        if system in ("Linux", "Darwin", "Windows"):
            self._add_result("OS Compatibility", ValidationSeverity.INFO,
                           f"Running on {system} {platform.release()}")
        else:
            self._add_result("OS Compatibility", ValidationSeverity.WARN,
                           f"Untested OS: {system}")

    def _check_python_version(self) -> None:
        """Check Python version meets requirements."""
        version = sys.version_info
        if version >= (3, 10):
            self._add_result("Python Version", ValidationSeverity.INFO,
                           f"Python {version.major}.{version.minor}.{version.micro} (supported)")
        else:
            self._add_result("Python Version", ValidationSeverity.ERROR,
                           f"Python {version.major}.{version.minor} requires 3.10+",
                           remediation="Upgrade Python to 3.10 or higher")

    def _check_docker_cli(self) -> None:
        """Check Docker CLI availability."""
        docker_path = shutil.which("docker")
        if docker_path:
            try:
                result = subprocess.run(["docker", "--version"], capture_output=True, text=True, timeout=5)
                if result.returncode == 0:
                    self._add_result("Docker CLI", ValidationSeverity.INFO,
                                   f"Found at {docker_path}: {result.stdout.strip()}")
                    return
            except Exception:
                pass
        self._add_result("Docker CLI", ValidationSeverity.ERROR,
                       "Docker CLI not found in PATH",
                       remediation="Install Docker Desktop (Windows/Mac) or Docker Engine (Linux)")

    def _check_docker_daemon(self) -> None:
        """Check Docker daemon responsiveness."""
        try:
            result = subprocess.run(["docker", "info"], capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                self._add_result("Docker Daemon", ValidationSeverity.INFO,
                               "Docker daemon is running and responsive")
            else:
                self._add_result("Docker Daemon", ValidationSeverity.ERROR,
                               "Docker daemon not responsive",
                               details={"stderr": result.stderr},
                               remediation="Start Docker Desktop or Docker service")
        except subprocess.TimeoutExpired:
            self._add_result("Docker Daemon", ValidationSeverity.ERROR,
                           "Docker daemon timeout",
                           remediation="Check Docker Desktop is running")
        except Exception as e:
            self._add_result("Docker Daemon", ValidationSeverity.ERROR,
                           f"Docker daemon check failed: {e}")

    def _check_docker_compose(self) -> None:
        """Check Docker Compose plugin availability."""
        try:
            # Try docker compose (v2 plugin)
            result = subprocess.run(["docker", "compose", "version"], capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                self._add_result("Docker Compose", ValidationSeverity.INFO,
                               f"Available: {result.stdout.strip()}")
                return
        except Exception:
            pass

        try:
            # Try docker-compose (v1 standalone)
            result = subprocess.run(["docker-compose", "--version"], capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                self._add_result("Docker Compose", ValidationSeverity.INFO,
                               f"Available (v1): {result.stdout.strip()}")
                return
        except Exception:
            pass

        self._add_result("Docker Compose", ValidationSeverity.ERROR,
                       "Docker Compose not available",
                       remediation="Install Docker Compose plugin or standalone")

    def _check_permissions(self) -> None:
        """Check required permissions."""
        if platform.system() == "Windows":
            # On Windows, check if we can run docker
            try:
                result = subprocess.run(["docker", "ps"], capture_output=True, text=True, timeout=5)
                if result.returncode == 0:
                    self._add_result("Permissions", ValidationSeverity.INFO,
                                   "Docker accessible without elevated privileges")
                else:
                    self._add_result("Permissions", ValidationSeverity.WARN,
                                   "May need to run in elevated terminal or add user to docker group")
            except Exception:
                self._add_result("Permissions", ValidationSeverity.WARN,
                               "Could not verify Docker permissions")
        else:
            # On Linux/macOS, check docker group membership
            import grp
            try:
                docker_group = grp.getgrnam("docker")
                user_groups = [g.gr_name for g in grp.getgrall() if os.getlogin() in g.gr_mem]
                if "docker" in user_groups or os.geteuid() == 0:
                    self._add_result("Permissions", ValidationSeverity.INFO,
                                   "User has Docker permissions")
                else:
                    self._add_result("Permissions", ValidationSeverity.WARN,
                                   "User not in docker group",
                                   remediation="Add user to docker group: sudo usermod -aG docker $USER")
            except Exception:
                self._add_result("Permissions", ValidationSeverity.INFO,
                               "Could not verify group membership")

    # --- B. Configuration Validation ---

    def _check_compose_files(self) -> None:
        """Check docker-compose.yml exists."""
        compose_file = self.project_root / "docker-compose.yml"
        if compose_file.exists():
            self._add_result("Compose File", ValidationSeverity.INFO,
                           f"Found: {compose_file}")
        else:
            self._add_result("Compose File", ValidationSeverity.ERROR,
                           "docker-compose.yml not found",
                           remediation="Ensure you are in the MEMORA project root")

    def _check_dockerfile(self) -> None:
        """Check Dockerfile exists."""
        dockerfile = self.project_root / "Dockerfile"
        if dockerfile.exists():
            self._add_result("Dockerfile", ValidationSeverity.INFO,
                           f"Found: {dockerfile}")
        else:
            self._add_result("Dockerfile", ValidationSeverity.ERROR,
                           "Dockerfile not found",
                           remediation="Ensure you are in the MEMORA project root")

    def _check_env_files(self) -> None:
        """Check environment files exist."""
        env_docker = self.project_root / ".env.docker"
        env_example = self.project_root / ".env.example"

        if env_docker.exists():
            self._add_result("Docker Env Template", ValidationSeverity.INFO,
                           f"Found: {env_docker}")
        else:
            self._add_result("Docker Env Template", ValidationSeverity.WARN,
                           ".env.docker not found")

        if env_example.exists():
            self._add_result("Env Example", ValidationSeverity.INFO,
                           f"Found: {env_example}")

        # Check for actual .env (user config)
        env_file = self.project_root / ".env"
        if env_file.exists():
            self._add_result("User Config (.env)", ValidationSeverity.INFO,
                           f"Found: {env_file}")
        else:
            self._add_result("User Config (.env)", ValidationSeverity.WARN,
                           ".env not found - using defaults",
                           remediation="Copy .env.example to .env and customize")

    def _check_required_env_vars(self) -> None:
        """Check required environment variables are set."""
        required = ["VAULT_PATH"]
        missing = []

        # Load .env file if exists
        env_file = self.project_root / ".env"
        env_vars = {}
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env_vars[k.strip()] = v.strip()

        for var in required:
            if var not in env_vars:
                missing.append(var)

        if not missing:
            self._add_result("Required Env Vars", ValidationSeverity.INFO,
                           "All required variables set")
        else:
            self._add_result("Required Env Vars", ValidationSeverity.ERROR,
                           f"Missing: {', '.join(missing)}",
                           remediation=f"Set {', '.join(missing)} in .env file")

    def _check_ollama_mode(self) -> None:
        """Check OLLAMA_MODE is valid."""
        mode = self.config.ollama_mode
        if mode in ("host", "container"):
            self._add_result("Ollama Mode", ValidationSeverity.INFO,
                           f"Mode: {mode}")
        else:
            self._add_result("Ollama Mode", ValidationSeverity.ERROR,
                           f"Invalid mode: {mode}",
                           remediation="Set OLLAMA_MODE to 'host' or 'container'")

    def _check_vault_path(self) -> None:
        """Check vault path exists and is accessible."""
        vault_path = self.config.vault_path

        # Handle Windows Docker Desktop paths (/host_mnt/c/...)
        # These are valid inside containers but may not exist on host filesystem
        vault_str = str(vault_path)
        is_docker_desktop_path = vault_str.startswith("/host_mnt/") or vault_str.startswith("/mnt/")

        if not vault_path.exists():
            if is_docker_desktop_path:
                # Docker Desktop paths may not exist on host but are valid in container
                self._add_result("Vault Path", ValidationSeverity.WARN,
                               f"Docker Desktop path (may not exist on host): {vault_path}",
                               remediation="Ensure this path is correct for Docker Desktop bind mount")
            else:
                self._add_result("Vault Path", ValidationSeverity.ERROR,
                               f"Vault path does not exist: {vault_path}",
                               remediation="Set correct VAULT_PATH in .env")
                return
        else:
            # Path exists - check for .obsidian
            obsidian_dir = vault_path / ".obsidian"
            if not obsidian_dir.exists():
                self._add_result("Vault Path", ValidationSeverity.ERROR,
                               f"No .obsidian directory at {vault_path}",
                               remediation="Ensure VAULT_PATH points to Obsidian vault root")
                return

            # Check read access
            try:
                test_file = vault_path / ".memora_access_test"
                test_file.write_text("test")
                test_file.unlink()
                write_access = True
            except Exception:
                write_access = False

            # Count markdown files
            try:
                from memora.ingestion.vault_reader import VaultReader
                vault_reader = VaultReader(vault_path=vault_path)
                md_files = vault_reader.list_files([".md"])
                md_count = len(md_files)
            except Exception:
                md_count = 0

            details = {"path": str(vault_path), "file_count": md_count, "writable": write_access}
            warnings = []
            if md_count == 0:
                warnings.append("No .md files found in vault")
            if not write_access and not is_docker_desktop_path:
                warnings.append("Vault directory not writable (read-only is OK for indexing)")

            if warnings:
                self._add_result("Vault Path", ValidationSeverity.WARN,
                               f"Vault accessible ({md_count} .md files): {'; '.join(warnings)}",
                               details=details,
                               remediation="Review warnings above")
            else:
                self._add_result("Vault Path", ValidationSeverity.INFO,
                               f"Valid vault: {vault_path} ({md_count} .md files)",
                               details=details)

    def _validate_docker_bind_mount(self) -> None:
        """Validate Docker bind mount configuration for vault path."""
        vault_path = self.config.vault_path
        vault_str = str(vault_path)

        # Normalize path for validation: convert Windows backslashes to forward slashes
        # This handles the case where Path() on Windows returns native backslash separators
        normalized_str = vault_str.replace("\\", "/")

        # Check for common Windows path issues in Docker
        issues = []
        warnings = []

        # Check for spaces in path (can cause issues with Docker volumes)
        if " " in normalized_str:
            warnings.append(f"Path contains spaces: '{normalized_str}' — ensure proper quoting in Docker")

        # Check for Windows-style backslashes in original (indicates potential issues)
        # But Windows drive-letter paths (C:\, D:\) are valid for Docker Desktop
        has_backslashes = "\\" in vault_str
        is_windows_drive_path = len(vault_str) >= 3 and vault_str[1] == ":" and vault_str[2] in ("/", "\\")

        if has_backslashes and not is_windows_drive_path:
            issues.append(f"Path contains backslashes: '{vault_str}' — use forward slashes for Docker")

        # Check for Windows drive letter format (C:/) vs Docker Desktop format (/host_mnt/c/)
        if normalized_str.startswith("/host_mnt/"):
            # Docker Desktop format - validate structure
            if not normalized_str.startswith("/host_mnt/c/") and not normalized_str.startswith("/host_mnt/d/"):
                warnings.append(f"Unusual Docker Desktop path format: {normalized_str}")
        elif normalized_str.startswith("C:/") or normalized_str.startswith("D:/") or normalized_str.startswith("/mnt/c/") or normalized_str.startswith("/mnt/d/"):
            # Windows absolute path with forward slashes - compatible with Docker Desktop
            # Docker Desktop accepts C:/ style paths for bind mounts (translates to /host_mnt/c/)
            pass  # Valid format, no warning needed
        elif is_windows_drive_path:
            # Windows drive-letter path with backslashes (e.g., C:\Users\...) - valid for Docker Desktop
            # Docker Desktop accepts C:\ style paths for bind mounts
            pass  # Valid format, no warning needed

        if issues:
            self._add_result("Docker Bind Mount", ValidationSeverity.ERROR,
                           "; ".join(issues),
                           remediation="Fix path format for Docker compatibility")
        elif warnings:
            self._add_result("Docker Bind Mount", ValidationSeverity.WARN,
                           "; ".join(warnings),
                           details={"path": normalized_str},
                           remediation="Review path format for Docker Desktop compatibility")
        else:
            self._add_result("Docker Bind Mount", ValidationSeverity.INFO,
                           f"Path format compatible: {normalized_str}")

    def _check_volume_config(self) -> None:
        """Check Docker volume configuration."""
        # Verify named volumes in compose
        compose_file = self.project_root / "docker-compose.yml"
        if compose_file.exists():
            content = compose_file.read_text()
            required_volumes = ["chromadb-data", "sqlite-data", "logs-data"]
            missing = [v for v in required_volumes if v not in content]
            if not missing:
                self._add_result("Volume Config", ValidationSeverity.INFO,
                               "All required volumes defined")
            else:
                self._add_result("Volume Config", ValidationSeverity.WARN,
                               f"Missing volumes: {', '.join(missing)}")

    def _check_compose_config(self) -> None:
        """Validate Docker Compose configuration resolves."""
        profiles = self._get_compose_profiles()
        try:
            result = subprocess.run(
                ["docker", "compose", "--env-file", ".env.docker", "--profile", ",".join(profiles), "config"],
                cwd=self.project_root,
                capture_output=True, text=True, timeout=15
            )
            if result.returncode == 0:
                self._add_result("Compose Config", ValidationSeverity.INFO,
                               "Configuration validates successfully")
            else:
                self._add_result("Compose Config", ValidationSeverity.ERROR,
                               "Configuration validation failed",
                               details={"stderr": result.stderr, "exit_code": result.returncode},
                               remediation="Check docker-compose.yml syntax and .env.docker variables")
        except FileNotFoundError:
            self._add_result("Compose Config", ValidationSeverity.ERROR,
                           "Docker Compose not available",
                           remediation="Install Docker Compose")
        except subprocess.TimeoutExpired:
            self._add_result("Compose Config", ValidationSeverity.ERROR,
                           "Compose config validation timed out")
        except Exception as e:
            self._add_result("Compose Config", ValidationSeverity.ERROR,
                           f"Compose config check failed: {e}")

    def _get_compose_profiles(self) -> List[str]:
        """Determine compose profiles from config (mirrors ComposeManager)."""
        profiles = ["http"]
        if self.config.ollama_mode == "container":
            profiles.append("ollama")
        return profiles

    # --- C. Ollama Validation ---

    def _check_ollama_connectivity(self) -> None:
        """Check Ollama connectivity based on configured mode."""
        mode = self.config.ollama_mode

        if mode == "host":
            # For Docker host mode, check the local host endpoint
            # The Docker Desktop gateway endpoint (host.docker.internal) only works from inside containers
            # We check it as a warning for informational purposes
            docker_ollama_host = self._get_docker_ollama_host()
            if docker_ollama_host:
                self._check_ollama_at_host(docker_ollama_host, "Ollama (Docker Host)", as_warning=True)
            # Check the local host endpoint - this is the one that matters for host-mode operation
            self._check_host_ollama()
        else:
            self._check_container_ollama()

    def _get_docker_ollama_host(self) -> Optional[str]:
        """Extract OLLAMA_HOST from .env.docker for host mode."""
        env_docker = self.project_root / ".env.docker"
        if not env_docker.exists():
            return None
        try:
            for line in env_docker.read_text().splitlines():
                line = line.strip()
                if line.startswith("OLLAMA_HOST=") and not line.startswith("#"):
                    return line.split("=", 1)[1].strip()
        except Exception:
            pass
        return None

    def _check_ollama_at_host(self, host: str, name: str, as_warning: bool = False) -> None:
        """Check Ollama connectivity at a specific host."""
        try:
            import httpx
            response = httpx.get(f"{host}/api/tags", timeout=5.0)
            if response.status_code == 200:
                models = response.json().get("models", [])
                model_names = [m.get("name", "") for m in models]
                model_available = any(self.config.embedding_model in m for m in model_names)

                if model_available:
                    severity = ValidationSeverity.WARN if as_warning else ValidationSeverity.INFO
                    self._add_result(name, severity,
                                   f"Connected to {host}, model '{self.config.embedding_model}' available",
                                   details={"models": len(model_names)})
                else:
                    severity = ValidationSeverity.WARN if as_warning else ValidationSeverity.WARN
                    self._add_result(name, severity,
                                   f"Connected to {host} but model '{self.config.embedding_model}' not found",
                                   details={"available_models": model_names},
                                   remediation=f"Run: ollama pull {self.config.embedding_model}")
            else:
                severity = ValidationSeverity.WARN if as_warning else ValidationSeverity.ERROR
                self._add_result(name, severity,
                               f"Ollama returned {response.status_code}",
                               remediation="Check Ollama is running")
        except httpx.ConnectError:
            severity = ValidationSeverity.WARN if as_warning else ValidationSeverity.ERROR
            self._add_result(name, severity,
                           f"Cannot connect to Ollama at {host}",
                           remediation="Start Ollama: 'ollama serve' or check OLLAMA_HOST in .env.docker")
        except Exception as e:
            severity = ValidationSeverity.WARN if as_warning else ValidationSeverity.ERROR
            self._add_result(name, severity,
                           f"Connection error: {e}")

    def _check_host_ollama(self) -> None:
        """Check host Ollama availability."""
        host = self.config.ollama_host
        try:
            import httpx
            response = httpx.get(f"{host}/api/tags", timeout=5.0)
            if response.status_code == 200:
                models = response.json().get("models", [])
                model_names = [m.get("name", "") for m in models]
                model_available = any(self.config.embedding_model in m for m in model_names)

                if model_available:
                    self._add_result("Ollama (Host)", ValidationSeverity.INFO,
                                   f"Connected to {host}, model '{self.config.embedding_model}' available",
                                   details={"models": len(model_names)})
                else:
                    self._add_result("Ollama (Host)", ValidationSeverity.WARN,
                                   f"Connected to {host} but model '{self.config.embedding_model}' not found",
                                   details={"available_models": model_names},
                                   remediation=f"Run: ollama pull {self.config.embedding_model}")
            else:
                self._add_result("Ollama (Host)", ValidationSeverity.ERROR,
                               f"Ollama returned {response.status_code}",
                               remediation="Check Ollama is running: 'ollama serve'")
        except httpx.ConnectError:
            self._add_result("Ollama (Host)", ValidationSeverity.ERROR,
                           f"Cannot connect to Ollama at {host}",
                           remediation="Start Ollama: 'ollama serve' or check OLLAMA_HOST")
        except Exception as e:
            self._add_result("Ollama (Host)", ValidationSeverity.ERROR,
                           f"Connection error: {e}")

    def _check_container_ollama(self) -> None:
        """Check containerized Ollama."""
        # Check if ollama service is defined in compose
        compose_file = self.project_root / "docker-compose.yml"
        if not compose_file.exists():
            return

        content = compose_file.read_text()
        if "ollama:" not in content:
            self._add_result("Ollama (Container)", ValidationSeverity.ERROR,
                           "Ollama service not defined in docker-compose.yml",
                           remediation="Add ollama service to compose or use host mode")
            return

        # Check if container is running
        try:
            result = subprocess.run(
                ["docker", "ps", "--filter", "name=memora-ollama", "--format", "{{.Status}}"],
                capture_output=True, text=True, timeout=5
            )
            if result.stdout.strip():
                self._add_result("Ollama (Container)", ValidationSeverity.INFO,
                               f"Container running: {result.stdout.strip()}")
            else:
                self._add_result("Ollama (Container)", ValidationSeverity.WARN,
                               "Ollama container not running",
                               remediation="Start with: docker compose --profile ollama up -d")
        except Exception as e:
            self._add_result("Ollama (Container)", ValidationSeverity.WARN,
                           f"Could not check container: {e}")

    # --- D. Networking Validation ---

    def _check_port_availability(self) -> None:
        """Check required ports are available."""
        port = self.config.mcp_port
        host = self.config.mcp_host

        # Check if port is already in use
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        try:
            result = sock.connect_ex((host if host != "0.0.0.0" else "127.0.0.1", port))
            if result == 0:
                # Port in use - check if it's our container
                self._add_result(f"Port {port}", ValidationSeverity.WARN,
                               f"Port {port} already in use",
                               details={"host": host, "port": port},
                               remediation="Check if existing MEMORA container is healthy")
            else:
                self._add_result(f"Port {port}", ValidationSeverity.INFO,
                               f"Port {port} available")
        finally:
            sock.close()

    def _check_existing_containers(self) -> None:
        """Check for existing MEMORA containers."""
        try:
            result = subprocess.run(
                ["docker", "ps", "-a", "--filter", "name=memora", "--format", "{{.Names}}\t{{.Status}}"],
                capture_output=True, text=True, timeout=5
            )
            if result.stdout.strip():
                containers = result.stdout.strip().split("\n")
                for c in containers:
                    if c.strip():
                        self._add_result("Existing Containers", ValidationSeverity.INFO,
                                       f"Found: {c}")
        except Exception:
            pass

    # --- E. Storage Validation ---

    def _check_storage_directories(self) -> None:
        """Check storage directories exist and are writable."""
        paths = [
            ("Data dir", self.config.data_dir),
            ("ChromaDB", self.config.chroma_path),
            ("SQLite", self.config.sqlite_path.parent),
        ]

        for name, path in paths:
            if not path.exists():
                try:
                    path.mkdir(parents=True, exist_ok=True)
                    self._add_result(f"Storage: {name}", ValidationSeverity.INFO,
                                   f"Created: {path}")
                except Exception as e:
                    self._add_result(f"Storage: {name}", ValidationSeverity.ERROR,
                                   f"Cannot create {path}: {e}")
            else:
                # Check write permission
                test_file = path / ".memora_write_test"
                try:
                    test_file.write_text("test")
                    test_file.unlink()
                    self._add_result(f"Storage: {name}", ValidationSeverity.INFO,
                                   f"Writable: {path}")
                except Exception:
                    self._add_result(f"Storage: {name}", ValidationSeverity.WARN,
                                   f"Not writable: {path}")

    def _check_volume_mounts(self) -> None:
        """Check volume mount configuration."""
        # Verify VAULT_PATH mount
        vault_path = self.config.vault_path
        if vault_path.exists():
            self._add_result("Vault Mount", ValidationSeverity.INFO,
                           f"Source exists: {vault_path}")
        else:
            self._add_result("Vault Mount", ValidationSeverity.ERROR,
                           f"Vault path not found: {vault_path}",
                           remediation="Check VAULT_PATH in .env and .env.docker")


def print_preflight_report(report: PreflightReport) -> None:
    """Print formatted preflight validation report."""
    console.print("\n" + "=" * 60)
    console.print("     MEMORA PREFLIGHT VALIDATION REPORT")
    console.print("=" * 60 + "\n")

    summary = report.get_summary()

    for result in report.results:
        if result.severity == ValidationSeverity.ERROR:
            style = "red"
            prefix = "✗"
        elif result.severity == ValidationSeverity.WARN:
            style = "yellow"
            prefix = "⚠"
        else:
            style = "green"
            prefix = "✓"

        console.print(f"[{style}]{prefix} {result.name}[/{style}]")
        if result.message:
            console.print(f"      {result.message}")
        if result.remediation and result.severity in (ValidationSeverity.WARN, ValidationSeverity.ERROR):
            console.print(f"      [dim]→ {result.remediation}[/dim]")

    console.print()
    console.print("=" * 60)
    console.print(f"SUMMARY:  ERROR: {summary['ERROR']}  WARN: {summary['WARN']}  INFO: {summary['INFO']}")
    console.print("=" * 60)


# =========================================================================
# Docker Compose Operations
# =========================================================================

class ComposeManager:
    """Manage Docker Compose operations for MEMORA."""

    def __init__(self, project_root: Path, config: MemoraConfig):
        self.project_root = project_root
        self.config = config
        # Configurable timeouts (can be overridden)
        self.build_timeout = 300  # 5 minutes for build
        self.compose_timeout = 120  # 2 minutes for compose commands
        self.health_timeout = 120  # 2 minutes for health checks
        self.health_interval = 5  # 5 seconds between health checks
        self.startup_timeout = 60  # 1 minute for service startup
        # Track resources created by this invocation for safe rollback
        self._started_containers: List[str] = []
        self._created_networks: List[str] = []

    def _run_compose(self, args: List[str], capture: bool = True, timeout: int = None) -> subprocess.CompletedProcess:
        """Run docker compose command with .env.docker for environment interpolation."""
        # Always include --env-file .env.docker for proper environment variable interpolation
        # This ensures ${OLLAMA_MODE:-host}, ${OLLAMA_HOST:-...}, etc. are resolved from .env.docker
        cmd = ["docker", "compose", "--env-file", ".env.docker"] + args
        try:
            return subprocess.run(
                cmd,
                cwd=self.project_root,
                capture_output=capture,
                text=True,
                timeout=timeout or self.compose_timeout
            )
        except FileNotFoundError:
            # Docker not installed - return failed result
            return subprocess.CompletedProcess(cmd, 1, "", "docker not found")
        except subprocess.TimeoutExpired:
            return subprocess.CompletedProcess(cmd, 1, "", f"timeout after {timeout or self.compose_timeout}s")

    def _get_profiles(self) -> List[str]:
        """Determine required compose profiles based on configuration."""
        profiles = ["http"]
        if self.config.ollama_mode == "container":
            profiles.append("ollama")
        return profiles

    def get_service_state(self) -> Dict[str, str]:
        """Get current state of MEMORA services before startup."""
        containers = self.ps()
        state = {}
        for c in containers:
            if c.name in ("memora-http", "memora-ollama"):
                state[c.name] = c.status
        return state

    def build(self, timeout: int = None) -> bool:
        """Build the MEMORA image with configurable timeout."""
        console.print("[bold]Building MEMORA image...[/bold]")
        profiles = self._get_profiles()
        args = ["--profile", ",".join(profiles), "build"]
        timeout = timeout or self.build_timeout
        result = self._run_compose(args, capture=False, timeout=timeout)
        return result.returncode == 0

    def up(self, detach: bool = True) -> bool:
        """Start MEMORA services."""
        console.print("[bold]Starting MEMORA services...[/bold]")
        profiles = self._get_profiles()
        args = ["--profile", ",".join(profiles), "up"]
        if detach:
            args.append("-d")
        result = self._run_compose(args, capture=False, timeout=self.startup_timeout)
        return result.returncode == 0

    def down(self, remove_volumes: bool = False) -> bool:
        """Stop MEMORA services."""
        console.print("[bold]Stopping MEMORA services...[/bold]")
        profiles = self._get_profiles()
        args = ["--profile", ",".join(profiles), "down"]
        if remove_volumes:
            args.append("-v")
        result = self._run_compose(args, capture=False)
        return result.returncode == 0

    def restart(self) -> bool:
        """Restart MEMORA services."""
        console.print("[bold]Restarting MEMORA services...[/bold]")
        profiles = self._get_profiles()
        args = ["--profile", ",".join(profiles), "restart"]
        result = self._run_compose(args, capture=False)
        return result.returncode == 0

    def ps(self) -> List[ContainerStatus]:
        """Get container statuses."""
        profiles = self._get_profiles()
        args = ["--profile", ",".join(profiles), "ps", "--format", "json"]
        result = self._run_compose(args)
        containers = []

        if result.returncode == 0 and result.stdout.strip():
            for line in result.stdout.strip().split("\n"):
                if line.strip():
                    try:
                        data = json.loads(line)
                        containers.append(ContainerStatus(
                            name=data.get("Names", ""),
                            status=data.get("State", ""),
                            health=data.get("Health", ""),
                            ports=data.get("Ports", "").split(", ") if data.get("Ports") else [],
                            image=data.get("Image", "")
                        ))
                    except json.JSONDecodeError:
                        pass
        return containers

    def logs(self, service: str = "memora-http", follow: bool = False, tail: int = 100) -> bool:
        """Get service logs."""
        profiles = self._get_profiles()
        args = ["--profile", ",".join(profiles), "logs"]
        if follow:
            args.append("-f")
        if tail:
            args.extend(["--tail", str(tail)])
        args.append(service)
        result = self._run_compose(args, capture=False)
        return result.returncode == 0

    def wait_healthy(self, timeout: int = None, interval: int = None) -> bool:
        """Wait for containers to become healthy."""
        timeout = timeout or self.health_timeout
        interval = interval or self.health_interval
        console.print("[bold]Waiting for health checks...[/bold]")
        start = time.time()

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("Checking container health...", total=None)

            while time.time() - start < timeout:
                containers = self.ps()
                all_healthy = True

                for c in containers:
                    if c.name in ("memora-http", "memora-ollama"):
                        if c.status != "running":
                            all_healthy = False
                            break
                        if c.health and "healthy" not in c.health.lower():
                            all_healthy = False
                            break

                if all_healthy and containers:
                    progress.update(task, completed=True)
                    console.print("[green]All containers healthy![/green]")
                    return True

                time.sleep(interval)

        console.print("[red]Timeout waiting for health checks[/red]")
        return False

    def verify_health_endpoints(self) -> bool:
        """Verify MEMORA HTTP health endpoints."""
        import urllib.request
        import urllib.error

        host = self.config.mcp_host if self.config.mcp_host != "0.0.0.0" else "127.0.0.1"
        port = self.config.mcp_port
        base_url = f"http://{host}:{port}"

        endpoints = [
            ("/health/live", "Liveness"),
            ("/health/ready", "Readiness"),
            ("/health/ollama", "Ollama"),
            ("/health/storage", "Storage"),
        ]

        console.print("[bold]Verifying health endpoints...[/bold]")
        all_ok = True

        for endpoint, name in endpoints:
            url = f"{base_url}{endpoint}"
            try:
                req = urllib.request.Request(url)
                response = urllib.request.urlopen(req, timeout=5)
                data = json.loads(response.read().decode())
                status = data.get("status", "unknown")
                if status in ("alive", "ready", "healthy"):
                    console.print(f"  [green]✓[/green] {name}: {status}")
                else:
                    console.print(f"  [yellow]⚠[/yellow] {name}: {status}")
                    all_ok = False
            except Exception as e:
                console.print(f"  [red]✗[/red] {name}: {e}")
                all_ok = False

        return all_ok

    def rollback(self) -> bool:
        """Rollback: stop only containers that were started by this invocation."""
        console.print("[yellow]Rolling back startup...[/yellow]")
        # Stop containers that we know we started
        # For safety, we don't auto-remove networks/volumes on rollback
        # Just stop the services
        return self.down(remove_volumes=False)


# =========================================================================
# Startup Orchestration
# =========================================================================

def _create_startup_config(config: MemoraConfig) -> StartupConfig:
    """Create StartupConfig from MemoraConfig with environment variable overrides."""
    startup_config = StartupConfig()

    # Allow environment variable overrides for timeouts
    if docker_timeout := os.environ.get("MEMORA_DOCKER_STARTUP_TIMEOUT"):
        try:
            startup_config.docker_startup_timeout = int(docker_timeout)
        except ValueError:
            pass

    if ollama_timeout := os.environ.get("MEMORA_OLLAMA_STARTUP_TIMEOUT"):
        try:
            startup_config.ollama_startup_timeout = int(ollama_timeout)
        except ValueError:
            pass

    if docker_path := os.environ.get("MEMORA_DOCKER_DESKTOP_PATH"):
        startup_config.docker_desktop_path = docker_path

    if ollama_exe := os.environ.get("MEMORA_OLLAMA_EXECUTABLE"):
        startup_config.ollama_executable = ollama_exe

    # Verbose mode from log level
    startup_config.verbose = config.log_level.upper() == "DEBUG"

    return startup_config


def _orchestrate_start_stdio(project_root: Path, config: MemoraConfig, skip_preflight: bool = False) -> int:
    """Orchestrate MEMORA startup in STDIO mode (direct server execution, no Docker)."""

    # Status flags for final report
    ollama_ok = False
    config_ok = False
    sqlite_ok = False
    chromadb_ok = False
    mcp_ok = False
    dependency_manager = None

    console.print("[bold]MEMORA Startup Sequence (STDIO Mode)[/bold]")
    console.print()

    # Step 1: Detect required dependencies (only Ollama for STDIO mode)
    console.print("[bold]Step 1/4: Detecting dependencies...[/bold]")
    startup_config = _create_startup_config(config)
    dependency_manager = DependencyLifecycleManager(config, startup_config, project_root)
    dependency_info = dependency_manager.detect_dependencies()

    # Log detection results (only Ollama relevant for STDIO)
    ollama_info = dependency_info.get(DependencyType.OLLAMA)

    if ollama_info:
        console.print(f"  Ollama: {'Found' if ollama_info.installed else 'Not Found'} ({ollama_info.version or 'unknown'})")
        console.print(f"  Ollama API: {'Running' if ollama_info.details.get('api_running') else 'Not Running'}")
        console.print(f"  Model '{config.embedding_model}': {'Available' if ollama_info.details.get('model_available') else 'Not Available'}")
        console.print(f"  Ollama Mode: {config.ollama_mode}")

    console.print()

    # Step 2: Start missing Ollama if needed (host mode only)
    if config.ollama_mode == "host":
        console.print("[bold]Step 2/4: Starting missing dependencies...[/bold]")
        start_success, start_errors = dependency_manager.start_missing_dependencies()

        if not start_success:
            for error in start_errors:
                console.print(f"  [red]✗[/red] {error}")
            console.print("\n[red]Failed to start required dependencies. Aborting startup.[/red]")
            return 1

        if start_errors:
            for error in start_errors:
                console.print(f"  [yellow]⚠[/yellow] {error}")

        console.print()

        # Step 3: Wait for Ollama readiness
        console.print("[bold]Step 3/4: Verifying dependency readiness...[/bold]")
        ready_success, ready_issues = dependency_manager.verify_dependencies_ready()

        if not ready_success:
            for issue in ready_issues:
                console.print(f"  [red]✗[/red] {issue}")
            console.print("\n[red]Dependencies not ready. Aborting startup.[/red]")
            return 1

        if ready_issues:
            for issue in ready_issues:
                console.print(f"  [yellow]⚠[/yellow] {issue}")

        ollama_ok = ready_success
    else:
        console.print("[dim]Container Ollama mode - Ollama managed by Docker (not applicable for STDIO)[/dim]")
        ollama_ok = True

    console.print()

    # Step 4: Preflight validation (storage, config, etc. - no Docker checks)
    console.print("[bold]Step 4/4: Running preflight validation...[/bold]")
    if not skip_preflight:
        validator = PreflightValidator(project_root, config)
        report = validator.run_all()

        # Extract key results for compact output
        for result in report.results:
            if result.name == "Storage: SQLite" and result.severity == ValidationSeverity.INFO:
                sqlite_ok = True
            elif result.name == "Storage: ChromaDB" and result.severity == ValidationSeverity.INFO:
                chromadb_ok = True

        if report.has_errors:
            # Filter out Docker-related errors for STDIO mode
            filtered_results = [r for r in report.results if "Docker" not in r.name and "Compose" not in r.name]
            if filtered_results and any(r.severity == ValidationSeverity.ERROR for r in filtered_results):
                print_preflight_report(report)
                console.print("\n[red]Preflight validation failed. Aborting startup.[/red]")
                if dependency_manager:
                    dependency_manager.cleanup_owned_processes()
                return 1

        if report.has_warnings:
            for result in report.results:
                if result.severity == ValidationSeverity.WARN and "Docker" not in result.name and "Compose" not in result.name:
                    console.print(f"[yellow]⚠[/yellow] {result.name}: {result.message}")
                    if result.remediation:
                        console.print(f"      [dim]→ {result.remediation}[/dim]")

        config_ok = True
    else:
        # Skip preflight but still validate storage
        try:
            from memora.storage.metadata_store import MetadataStore
            from memora.storage.vector_store import VectorStore
            MetadataStore(db_path=config.sqlite_path)
            VectorStore(persist_path=str(config.chroma_path))
            sqlite_ok = True
            chromadb_ok = True
            config_ok = True
        except Exception as e:
            console.print(f"[red]Storage validation failed: {e}[/red]")
            return 1

    # Ollama status for final report
    if config.ollama_mode == "host":
        ollama_ok = ollama_ok
    else:
        ollama_ok = True

    # Start the STDIO server directly
    console.print()
    console.print("[bold]Starting MEMORA STDIO server...[/bold]")

    # Ensure directories exist
    config.ensure_dirs()

    # Run the STDIO server directly (this blocks until shutdown)
    try:
        import subprocess
        import sys

        # Get the Python executable and run memora-server
        python_exe = sys.executable
        cmd = [python_exe, "-m", "memora.mcp.server"]

        console.print(f"[dim]Executing: {' '.join(cmd)}[/dim]")
        console.print()

        # Run the server - this blocks until the process exits
        # Note: In STDIO mode, the server communicates via stdin/stdout
        # We need to run it in the current process context
        from memora.mcp.server import main as server_main
        import asyncio

        console.print("[green]MEMORA STDIO server started successfully[/green]")
        console.print("[dim]Server is running. Press Ctrl+C to stop.[/dim]")
        console.print()

        # Run the server
        asyncio.run(server_main())

    except KeyboardInterrupt:
        console.print("\n[yellow]Shutdown requested[/yellow]")
    except Exception as e:
        console.print(f"[red]Server error: {e}[/red]")
        return 1
    finally:
        if dependency_manager:
            dependency_manager.cleanup_owned_processes()

    # Final startup report
    console.print()
    console.print("MEMORA STARTUP")
    console.print()
    console.print(f"  Docker: Not Required (STDIO mode)")
    console.print(f"  Ollama: {'Available' if ollama_ok else 'Not Available'}")
    console.print(f"  Configuration: {'Valid' if config_ok else 'Invalid'}")
    console.print(f"  SQLite: {'Healthy' if sqlite_ok else 'Unhealthy'}")
    console.print(f"  ChromaDB: {'Healthy' if chromadb_ok else 'Unhealthy'}")
    console.print(f"  MCP Server: {'Healthy' if mcp_ok else 'Unhealthy'}")
    console.print()
    console.print("MEMORA STDIO server stopped")

    return 0


def orchestrate_start(project_root: Path, config: MemoraConfig, skip_preflight: bool = False) -> int:
    """Orchestrate complete MEMORA startup sequence with automatic dependency management.

    Startup sequence:
    1. Load MEMORA configuration
    2. Perform static configuration checks
    3. Detect required dependencies (Docker, Ollama)
    4. Start missing dependencies
    5. Wait for dependency readiness
    6. Execute full preflight validation
    7. Validate Docker Compose configuration (if HTTP mode)
    8. Start MEMORA application (via Docker Compose for HTTP, direct for STDIO)
    9. Verify health
    10. Report successful startup
    """

    # Track whether we successfully started services for rollback
    services_started = False
    dependency_manager = None

    # Status flags for final report
    docker_ok = False
    ollama_ok = False
    config_ok = False
    sqlite_ok = False
    chromadb_ok = False
    mcp_ok = False

    console.print("[bold]MEMORA Startup Sequence[/bold]")
    console.print()

    # Check transport mode - STDIO runs directly, HTTP uses Docker Compose
    is_stdio_mode = config.mcp_transport == "stdio"

    if is_stdio_mode:
        console.print("[cyan]STDIO transport mode detected - running server directly (no Docker required)[/cyan]")
        return _orchestrate_start_stdio(project_root, config, skip_preflight)

    # HTTP mode - use Docker Compose (original logic)
    console.print("[cyan]HTTP transport mode detected - using Docker Compose[/cyan]")

    # Acquire startup lock to prevent concurrent startup
    startup_lock = StartupLock(project_root)
    if not startup_lock.acquire(timeout=30.0):
        console.print("[red]Another MEMORA startup is in progress. Please wait or stop the existing process.[/red]")
        return 1

    try:
        # Track whether we successfully started services for rollback
        services_started = False
        dependency_manager = None

        # Status flags for final report
        docker_ok = False
        ollama_ok = False
        config_ok = False
        sqlite_ok = False
        chromadb_ok = False
        mcp_ok = False

        console.print("[bold]MEMORA Startup Sequence[/bold]")
        console.print()

        # Step 1-2: Configuration already loaded, static checks done in preflight

        # Step 3: Detect required dependencies
        console.print("[bold]Step 1/5: Detecting dependencies...[/bold]")
        startup_config = _create_startup_config(config)
        dependency_manager = DependencyLifecycleManager(config, startup_config, project_root)
        dependency_info = dependency_manager.detect_dependencies()

        # Log detection results
        docker_info = dependency_info.get(DependencyType.DOCKER_DESKTOP)
        ollama_info = dependency_info.get(DependencyType.OLLAMA)

        if docker_info:
            console.print(f"  Docker CLI: {'Found' if docker_info.installed else 'Not Found'} ({docker_info.version or 'unknown'})")
            console.print(f"  Docker Desktop: {'Installed' if docker_info.details.get('docker_desktop_installed') else 'Not Installed'}")
            console.print(f"  Docker Daemon: {'Running' if docker_info.details.get('daemon_running') else 'Not Running'}")

        if ollama_info:
            console.print(f"  Ollama: {'Found' if ollama_info.installed else 'Not Found'} ({ollama_info.version or 'unknown'})")
            console.print(f"  Ollama API: {'Running' if ollama_info.details.get('api_running') else 'Not Running'}")
            console.print(f"  Model '{config.embedding_model}': {'Available' if ollama_info.details.get('model_available') else 'Not Available'}")
            console.print(f"  Ollama Mode: {config.ollama_mode}")

        console.print()

        # Step 4: Start missing dependencies
        console.print("[bold]Step 2/5: Starting missing dependencies...[/bold]")
        start_success, start_errors = dependency_manager.start_missing_dependencies()

        if not start_success:
            for error in start_errors:
                console.print(f"  [red]✗[/red] {error}")
            console.print("\n[red]Failed to start required dependencies. Aborting startup.[/red]")
            return 1

        if start_errors:
            for error in start_errors:
                console.print(f"  [yellow]⚠[/yellow] {error}")

        console.print()

        # Step 5: Wait for dependency readiness
        console.print("[bold]Step 3/5: Verifying dependency readiness...[/bold]")
        ready_success, ready_issues = dependency_manager.verify_dependencies_ready()

        if not ready_success:
            for issue in ready_issues:
                console.print(f"  [red]✗[/red] {issue}")
            console.print("\n[red]Dependencies not ready. Aborting startup.[/red]")
            return 1

        if ready_issues:
            for issue in ready_issues:
                console.print(f"  [yellow]⚠[/yellow] {issue}")

        # Docker is now ready - set flag
        docker_ok = True
        # Ollama readiness is determined by verify_dependencies_ready()
        # ready_success=True means all dependencies (including Ollama) are ready
        if config.ollama_mode == "host":
            ollama_ok = ready_success
        elif config.ollama_mode == "container":
            # Container mode - Ollama will be started by Docker Compose
            ollama_ok = True

        console.print()

        # Step 6: Execute full preflight validation
        if not skip_preflight:
            console.print("[bold]Step 4/5: Running preflight validation...[/bold]")
            validator = PreflightValidator(project_root, config)
            report = validator.run_all()

            # Extract key results for compact output
            for result in report.results:
                if result.name == "Compose Config" and result.severity == ValidationSeverity.INFO:
                    config_ok = True
                elif result.name == "Storage: SQLite" and result.severity == ValidationSeverity.INFO:
                    sqlite_ok = True
                elif result.name == "Storage: ChromaDB" and result.severity == ValidationSeverity.INFO:
                    chromadb_ok = True

            if report.has_errors:
                print_preflight_report(report)
                console.print("\n[red]Preflight validation failed. Aborting startup.[/red]")
                # Clean up any processes we started
                if dependency_manager:
                    dependency_manager.cleanup_owned_processes()
                return 1

            if report.has_warnings:
                # Only show warnings, not full report
                for result in report.results:
                    if result.severity == ValidationSeverity.WARN:
                        console.print(f"[yellow]⚠[/yellow] {result.name}: {result.message}")
                        if result.remediation:
                            console.print(f"      [dim]→ {result.remediation}[/dim]")

            # Ensure compose config is validated (may have been done in preflight)
            if not config_ok:
                try:
                    compose = ComposeManager(project_root, config)
                    profiles = compose._get_profiles()
                    result = subprocess.run(
                        ["docker", "compose", "--env-file", ".env.docker", "--profile", ",".join(profiles), "config"],
                        cwd=project_root, capture_output=True, text=True, timeout=15
                    )
                    if result.returncode == 0:
                        config_ok = True
                except Exception:
                    pass
        else:
            # Skip preflight but still validate compose config
            console.print("[bold]Step 4/5: Validating compose configuration...[/bold]")
            try:
                compose = ComposeManager(project_root, config)
                profiles = compose._get_profiles()
                result = subprocess.run(
                    ["docker", "compose", "--env-file", ".env.docker", "--profile", ",".join(profiles), "config"],
                    cwd=project_root, capture_output=True, text=True, timeout=15
                )
                if result.returncode == 0:
                    config_ok = True
                else:
                    console.print(f"[red]Compose config invalid: {result.stderr}[/red]")
                    if dependency_manager:
                        dependency_manager.cleanup_owned_processes()
                    return 1
            except Exception as e:
                console.print(f"[red]Compose config check failed: {e}[/red]")
                if dependency_manager:
                    dependency_manager.cleanup_owned_processes()
                return 1

        console.print()

        # Step 7-9: Build, start services, verify health
        console.print("[bold]Step 5/5: Starting MEMORA services...[/bold]")
        compose = ComposeManager(project_root, config)

        # 7. Build image if necessary
        if not compose.build():
            console.print("[red]Build failed[/red]")
            if dependency_manager:
                dependency_manager.cleanup_owned_processes()
            return 1

        # 8. Start services
        if not compose.up(detach=True):
            console.print("[red]Failed to start services[/red]")
            if dependency_manager:
                dependency_manager.cleanup_owned_processes()
            return 1
        services_started = True

        # 9. Wait for health checks
        if not compose.wait_healthy():
            console.print("[red]Health checks failed[/red]")
            compose.logs("memora-http", tail=50)
            console.print("[yellow]Rolling back due to health check failure...[/yellow]")
            compose.rollback()
            if dependency_manager:
                dependency_manager.cleanup_owned_processes()
            return 1

        # 10. Verify health endpoints (sets mcp_ok, sqlite_ok, chromadb_ok)
        if compose.verify_health_endpoints():
            mcp_ok = True
            sqlite_ok = True
            chromadb_ok = True
        else:
            console.print("[yellow]Some health endpoints degraded[/yellow]")

        console.print()

        # Final startup report - REQUIRED FORMAT
        console.print("MEMORA STARTUP")
        console.print()
        console.print(f"  Docker: {'Available' if docker_ok else 'Not Available'}")
        console.print(f"  Ollama: {'Available' if ollama_ok else 'Not Available'}")
        console.print(f"  Configuration: {'Valid' if config_ok else 'Invalid'}")
        console.print(f"  SQLite: {'Healthy' if sqlite_ok else 'Unhealthy'}")
        console.print(f"  ChromaDB: {'Healthy' if chromadb_ok else 'Unhealthy'}")
        console.print(f"  MCP Server: {'Healthy' if mcp_ok else 'Unhealthy'}")
        console.print()
        host = config.mcp_host if config.mcp_host != "0.0.0.0" else "127.0.0.1"
        console.print(f"MEMORA is ready at http://{host}:{config.mcp_port}")

        return 0
    finally:
        startup_lock.release()


def orchestrate_stop(project_root: Path, config: MemoraConfig, stop_dependencies: bool = False, remove_volumes: bool = False) -> int:
    """Orchestrate MEMORA shutdown (preserves all persistent volumes).

    By default, only stops MEMORA deployment containers.
    Does NOT automatically terminate:
    - Docker Desktop (user application)
    - Existing user-owned Ollama processes
    - Other unrelated user applications

    Use stop_dependencies=True to also stop MEMORA-owned dependency processes
    (e.g., Ollama started by MEMORA in host mode).
    """
    compose = ComposeManager(project_root, config)

    console.print("[bold]Stopping MEMORA services...[/bold]")

    # Check Docker availability first
    try:
        result = subprocess.run(["docker", "info"], capture_output=True, text=True, timeout=5)
        if result.returncode != 0:
            console.print("[yellow]Docker daemon not accessible - cannot stop containers[/yellow]")
            console.print("[dim]Persistent volumes are preserved (no -v flag used)[/dim]")
            return 0
    except FileNotFoundError:
        console.print("[yellow]Docker not installed - cannot stop containers[/yellow]")
        console.print("[dim]Persistent volumes are preserved (no -v flag used)[/dim]")
        return 0
    except Exception:
        console.print("[yellow]Docker unavailable - cannot stop containers[/yellow]")
        console.print("[dim]Persistent volumes are preserved (no -v flag used)[/dim]")
        return 0

    # Remove volumes only if explicitly requested
    if not compose.down(remove_volumes=remove_volumes):
        console.print("[red]Failed to stop services[/red]")
        return 1

    if remove_volumes:
        console.print("[yellow]Persistent volumes removed[/yellow]")
    else:
        console.print("[dim]Persistent volumes preserved: chromadb-data, sqlite-data, logs-data, ollama-models[/dim]")

    # Optionally stop MEMORA-owned dependency processes
    if stop_dependencies and config.ollama_mode == "host":
        console.print("[bold]Stopping MEMORA-owned dependencies...[/bold]")
        startup_config = _create_startup_config(config)
        dependency_manager = DependencyLifecycleManager(config, startup_config, project_root)
        # Detect to populate started_by_memora flags
        dependency_manager.detect_dependencies()
        if dependency_manager.cleanup_owned_processes():
            console.print("[green]MEMORA-owned dependencies stopped[/green]")
        else:
            console.print("[yellow]Some MEMORA-owned dependencies could not be stopped[/yellow]")

    console.print("[green]MEMORA stopped successfully[/green]")
    console.print("[dim]Persistent volumes preserved: chromadb-data, sqlite-data, logs-data, ollama-models[/dim]")
    if stop_dependencies:
        console.print("[dim]MEMORA-owned Ollama was stopped (Docker Desktop was NOT terminated)[/dim]")
    else:
        console.print("[dim]Docker Desktop and user-owned Ollama processes were NOT terminated[/dim]")
    return 0


def orchestrate_purge(project_root: Path, config: MemoraConfig, confirm_destroy: bool = False) -> int:
    """Orchestrate MEMORA purge - DESTRUCTIVE: removes all persistent volumes."""
    compose = ComposeManager(project_root, config)

    console.print("[bold red]WARNING: DESTRUCTIVE PURGE OPERATION[/bold red]")
    console.print("This will PERMANENTLY DELETE all persistent data:")
    console.print("  • chromadb-data  — ChromaDB vector database")
    console.print("  • sqlite-data    — SQLite metadata database")
    console.print("  • logs-data      — Service log files")
    console.print("  • ollama-models  — Ollama model cache (container mode)")
    console.print()

    if not confirm_destroy:
        console.print("[red]ERROR: Destructive purge requires explicit confirmation.[/red]")
        console.print("Use [bold]--confirm-destroy[/bold] flag to proceed.")
        console.print("Example: [bold]memora --purge --confirm-destroy[/bold]")
        return 1

    console.print("[yellow]Final confirmation required. This action CANNOT be undone.[/yellow]")
    if not typer.confirm("Are you absolutely sure you want to DELETE all persistent data?"):
        console.print("Aborted.")
        return 0

    console.print("[bold]Purging MEMORA services and volumes...[/bold]")
    if not compose.down(remove_volumes=True):
        console.print("[red]Failed to purge services[/red]")
        return 1

    console.print("[green]MEMORA purged successfully — all volumes removed[/green]")
    return 0


def orchestrate_restart(project_root: Path, config: MemoraConfig) -> int:
    """Orchestrate MEMORA restart."""
    compose = ComposeManager(project_root, config)

    console.print("[bold]Restarting MEMORA services...[/bold]")
    if not compose.restart():
        console.print("[red]Restart failed[/red]")
        return 1

    # Wait for health checks
    console.print()
    if not compose.wait_healthy():
        console.print("[red]Health checks failed after restart[/red]")
        return 1

    # Verify health endpoints
    console.print()
    if not compose.verify_health_endpoints():
        console.print("[yellow]Some health endpoints degraded[/yellow]")

    console.print("[green]MEMORA restarted successfully[/green]")
    return 0


def get_status(project_root: Path, config: MemoraConfig) -> int:
    """Get comprehensive status report."""
    compose = ComposeManager(project_root, config)
    containers = compose.ps()

    console.print(Panel.fit("[bold]MEMORA Status Report[/bold]", border_style="blue"))

    # Docker daemon status
    try:
        result = subprocess.run(["docker", "info"], capture_output=True, text=True, timeout=5)
        docker_status = "Running" if result.returncode == 0 else "Not accessible"
    except Exception:
        docker_status = "Error"

    console.print(f"\n[bold]Docker Daemon:[/bold] {docker_status}")

    # Container status
    if containers:
        table = Table(show_header=True, header_style="bold")
        table.add_column("Container")
        table.add_column("Status")
        table.add_column("Health")
        table.add_column("Ports")
        table.add_column("Image")

        for c in containers:
            status_style = "green" if c.status == "running" else "red"
            health = c.health or "N/A"
            health_style = "green" if "healthy" in health.lower() else ("yellow" if health else "red")

            table.add_row(
                c.name,
                f"[{status_style}]{c.status}[/{status_style}]",
                f"[{health_style}]{health}[/{health_style}]",
                ", ".join(c.ports) if c.ports else "N/A",
                c.image
            )
        console.print(table)
    else:
        console.print("\n[yellow]No MEMORA containers found[/yellow]")

    # MCP HTTP availability
    host = config.mcp_host if config.mcp_host != "0.0.0.0" else "127.0.0.1"
    port = config.mcp_port
    mcp_url = f"http://{host}:{port}"

    try:
        import urllib.request
        response = urllib.request.urlopen(f"{mcp_url}/health/ready", timeout=3)
        data = json.loads(response.read().decode())
        console.print(f"\n[bold]MCP HTTP:[/bold] [green]Available[/green] at {mcp_url}")
        console.print(f"  Readiness: {data.get('status', 'unknown')}")
    except Exception:
        console.print(f"\n[bold]MCP HTTP:[/bold] [red]Not available[/red] at {mcp_url}")

    # Ollama availability
    try:
        import httpx
        response = httpx.get(f"{config.ollama_host}/api/tags", timeout=3.0)
        if response.status_code == 200:
            models = response.json().get("models", [])
            model_names = [m.get("name", "") for m in models]
            model_available = any(config.embedding_model in m for m in model_names)
            console.print(f"\n[bold]Ollama:[/bold] [green]Connected[/green] at {config.ollama_host}")
            console.print(f"  Model '{config.embedding_model}': {'Available' if model_available else 'Not found'}")
            console.print(f"  Available models: {len(model_names)}")
        else:
            console.print(f"\n[bold]Ollama:[/bold] [red]Error {response.status_code}[/red]")
    except Exception:
        console.print(f"\n[bold]Ollama:[/bold] [red]Not accessible[/red] at {config.ollama_host}")

    # Storage
    console.print(f"\n[bold]Storage:[/bold]")
    console.print(f"  ChromaDB: {config.chroma_path}")
    console.print(f"  SQLite: {config.sqlite_path}")
    console.print(f"  Logs: {config.log_file or 'Not configured'}")

    # Vault
    console.print(f"\n[bold]Vault:[/bold] {config.vault_path}")
    console.print(f"  Valid: {'Yes' if config.validate_vault() else 'No'}")

    # Transport
    console.print(f"\n[bold]Transport:[/bold] {config.mcp_transport}")
    console.print(f"  Endpoint: {mcp_url}")

    return 0


# =========================================================================
# CLI Commands
# =========================================================================

@app.command()
def start(
    skip_preflight: bool = typer.Option(False, "--skip-preflight", help="Skip preflight validation"),
    no_build: bool = typer.Option(False, "--no-build", help="Skip image build"),
):
    """Start MEMORA with full preflight validation and orchestration."""
    project_root = discover_project_root()
    config = load_config(project_root)

    console.print(f"[bold]MEMORA Startup[/bold]")
    console.print(f"  Project root: {project_root}")
    console.print(f"  Config: {config.mcp_transport} on port {config.mcp_port}")

    if no_build:
        # Temporarily monkey-patch build to skip
        original_build = ComposeManager.build
        ComposeManager.build = lambda self: True

    exit_code = orchestrate_start(project_root, config, skip_preflight)
    raise typer.Exit(code=exit_code)


@app.command()
def stop(
    remove_volumes: bool = typer.Option(False, "--remove-volumes", "-v", help="Remove named volumes (DANGEROUS)"),
    stop_dependencies: bool = typer.Option(False, "--stop-dependencies", help="Also stop MEMORA-owned dependencies (Ollama in host mode)"),
):
    """Stop MEMORA services gracefully.

    By default, only stops MEMORA deployment containers.
    Docker Desktop and user-owned Ollama processes are NOT terminated.
    Use --stop-dependencies to also stop MEMORA-owned dependency processes.
    """
    project_root = discover_project_root()
    config = load_config(project_root)

    if remove_volumes:
        console.print("[red]WARNING: This will remove all persistent data![/red]")
        if not typer.confirm("Are you sure?"):
            console.print("Aborted.")
            raise typer.Exit(code=0)

    exit_code = orchestrate_stop(project_root, config, stop_dependencies=stop_dependencies, remove_volumes=remove_volumes)
    raise typer.Exit(code=exit_code)


@app.command()
def restart():
    """Restart MEMORA services with health verification."""
    project_root = discover_project_root()
    config = load_config(project_root)

    exit_code = orchestrate_restart(project_root, config)
    raise typer.Exit(code=exit_code)


@app.command()
def status():
    """Show comprehensive MEMORA status."""
    project_root = discover_project_root()
    config = load_config(project_root)

    exit_code = get_status(project_root, config)
    raise typer.Exit(code=exit_code)


@app.command()
def doctor(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed output"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
):
    """Run system diagnostics to verify MEMORA installation."""
    project_root = discover_project_root()
    config = load_config(project_root)

    report = run_doctor(config=config, verbose=verbose, json_output=json_output)

    if not json_output:
        raise typer.Exit(code=report.exit_code)


@app.command()
def logs(
    service: str = typer.Option("memora-http", "--service", "-s", help="Service name"),
    follow: bool = typer.Option(False, "--follow", "-f", help="Follow log output"),
    tail: int = typer.Option(100, "--tail", "-n", help="Number of lines to show"),
):
    """Show MEMORA service logs."""
    project_root = discover_project_root()
    config = load_config(project_root)

    compose = ComposeManager(project_root, config)
    success = compose.logs(service=service, follow=follow, tail=tail)

    if not success:
        console.print("[red]Failed to retrieve logs[/red]")
        raise typer.Exit(code=1)


@app.command()
def version():
    """Show MEMORA version information."""
    # Get version from pyproject.toml
    version = "0.1.0"
    try:
        import tomli
        with open(PROJECT_ROOT / "pyproject.toml", "rb") as f:
            data = tomli.load(f)
            version = data.get("project", {}).get("version", version)
    except Exception:
        pass

    console.print(f"MEMORA version: {version}")
    console.print(f"Python: {platform.python_version()}")
    console.print(f"Platform: {platform.platform()}")
    console.print(f"Project root: {PROJECT_ROOT}")


if __name__ == "__main__":
    app()