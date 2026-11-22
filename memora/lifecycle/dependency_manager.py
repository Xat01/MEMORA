"""
MEMORA Dependency Lifecycle Manager

Automatic dependency detection and startup for Docker Desktop and Ollama.
Handles Docker Desktop lifecycle, Ollama lifecycle, and process ownership tracking.
"""

import os
import sys
import shutil
import subprocess
import time
import platform
import socket
import signal
import json
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum
import threading

import httpx

from memora.config import MemoraConfig

# Module logger
logger = logging.getLogger("memora.lifecycle.dependency_manager")


class DependencyType(Enum):
    """Types of dependencies managed by MEMORA."""
    DOCKER_DESKTOP = "docker_desktop"
    OLLAMA = "ollama"


class DependencyState(Enum):
    """State of a managed dependency."""
    UNKNOWN = "unknown"
    NOT_INSTALLED = "not_installed"
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    FAILED = "failed"


@dataclass
class DependencyInfo:
    """Information about a managed dependency."""
    type: DependencyType
    state: DependencyState = DependencyState.UNKNOWN
    installed: bool = False
    executable_path: Optional[str] = None
    process_id: Optional[int] = None
    started_by_memora: bool = False
    version: Optional[str] = None
    error_message: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class StartupConfig:
    """Configuration for dependency startup."""
    # Docker Desktop settings
    docker_startup_timeout: int = 120  # seconds
    docker_startup_interval: int = 5  # seconds between checks
    docker_desktop_path: Optional[str] = None  # Auto-discover if None

    # Ollama settings
    ollama_startup_timeout: int = 60  # seconds
    ollama_startup_interval: int = 3  # seconds between checks
    ollama_executable: str = "ollama"  # Command or path (auto-detected if not specified)

    # General settings
    verbose: bool = False

    def __post_init__(self):
        """Auto-detect Ollama executable for Windows."""
        if self.ollama_executable == "ollama" and platform.system() == "Windows":
            # On Windows, Ollama is typically installed as ollama.exe
            self.ollama_executable = "ollama.exe"


class DockerDesktopDetector:
    """Detect and manage Docker Desktop on Windows."""

    # Known Docker Desktop installation paths
    DOCKER_DESKTOP_PATHS = [
        r"C:\Program Files\Docker\Docker\Docker Desktop.exe",
        r"C:\Program Files (x86)\Docker\Docker\Docker Desktop.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Docker\Docker\Docker Desktop.exe"),
        os.path.expandvars(r"%APPDATA%\Docker\Docker\Docker Desktop.exe"),
    ]

    def __init__(self, config: StartupConfig):
        self.config = config
        self._cached_executable: Optional[str] = None

    def is_docker_cli_available(self) -> bool:
        """Check if Docker CLI is available in PATH."""
        return shutil.which("docker") is not None

    def get_docker_version(self) -> Optional[str]:
        """Get Docker version if available."""
        try:
            result = subprocess.run(
                ["docker", "--version"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception:
            pass
        return None

    def is_daemon_running(self) -> bool:
        """Check if Docker daemon is responsive."""
        try:
            result = subprocess.run(
                ["docker", "info"],
                capture_output=True,
                text=True,
                timeout=10
            )
            return result.returncode == 0
        except Exception:
            return False

    def find_docker_desktop(self) -> Optional[str]:
        """Find Docker Desktop executable using reliable Windows installation discovery."""
        if self._cached_executable and Path(self._cached_executable).exists():
            logger.debug(f"Using cached Docker Desktop path: {self._cached_executable}")
            return self._cached_executable

        # Check configured path first
        if self.config.docker_desktop_path:
            path = Path(self.config.docker_desktop_path)
            if path.exists():
                self._cached_executable = str(path)
                logger.info(f"Found Docker Desktop at configured path: {path}")
                return self._cached_executable
            else:
                logger.warning(f"Configured Docker Desktop path does not exist: {path}")

        # Check known installation paths
        for path_str in self.DOCKER_DESKTOP_PATHS:
            path = Path(path_str)
            if path.exists():
                self._cached_executable = str(path)
                logger.info(f"Found Docker Desktop at known path: {path}")
                return self._cached_executable
            else:
                logger.debug(f"Docker Desktop not found at: {path}")

        # Try to find via Windows registry (for per-user installations)
        if platform.system() == "Windows":
            reg_path = self._find_via_registry()
            if reg_path:
                self._cached_executable = reg_path
                logger.info(f"Found Docker Desktop via registry: {reg_path}")
                return reg_path
            else:
                logger.debug("Docker Desktop not found in Windows registry")

        logger.warning("Docker Desktop executable not found in any known location")
        return None

    def _find_via_registry(self) -> Optional[str]:
        """Find Docker Desktop via Windows registry."""
        try:
            import winreg
            # Check user-specific installation
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Docker\Docker Desktop") as key:
                install_path, _ = winreg.QueryValueEx(key, "InstallPath")
                exe_path = Path(install_path) / "Docker Desktop.exe"
                if exe_path.exists():
                    return str(exe_path)
        except Exception:
            pass

        try:
            import winreg
            # Check system-wide installation
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Docker\Docker Desktop") as key:
                install_path, _ = winreg.QueryValueEx(key, "InstallPath")
                exe_path = Path(install_path) / "Docker Desktop.exe"
                if exe_path.exists():
                    return str(exe_path)
        except Exception:
            pass

        return None

    def is_docker_desktop_installed(self) -> bool:
        """Check if Docker Desktop is installed."""
        return self.find_docker_desktop() is not None

    def is_docker_desktop_running(self) -> bool:
        """Check if Docker Desktop process is running (not just daemon)."""
        if platform.system() != "Windows":
            # On Linux/macOS, Docker daemon running implies Docker is available
            return self.is_daemon_running()

        try:
            result = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq Docker Desktop.exe", "/FO", "CSV"],
                capture_output=True,
                text=True,
                timeout=5
            )
            # Check if Docker Desktop.exe appears in output (skip header)
            lines = result.stdout.strip().split('\n')
            return len(lines) > 1 and "Docker Desktop.exe" in result.stdout
        except Exception:
            return False

    def start_docker_desktop(self) -> Tuple[bool, Optional[int], Optional[str]]:
        """
        Start Docker Desktop and wait for daemon readiness.

        Returns:
            Tuple of (success, process_id, error_message)
        """
        exe_path = self.find_docker_desktop()
        if not exe_path:
            return False, None, "Docker Desktop not installed"

        # Check if already running
        if self.is_daemon_running():
            logger.info("Docker daemon already running")
            return True, None, None

        logger.info(f"Starting Docker Desktop from: {exe_path}")
        logger.debug(f"Platform: {platform.system()}, Command: [{exe_path}]")

        try:
            # Start Docker Desktop as background process
            # Use CREATE_NEW_PROCESS_GROUP on Windows to allow independent lifecycle
            if platform.system() == "Windows":
                creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP
                process = subprocess.Popen(
                    [exe_path],
                    creationflags=creation_flags,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            else:
                process = subprocess.Popen(
                    [exe_path],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )

            pid = process.pid
            logger.info(f"Docker Desktop process started with PID: {pid}")

            # Verify process is alive
            time.sleep(1)
            if platform.system() == "Windows":
                try:
                    result = subprocess.run(
                        ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV"],
                        capture_output=True, text=True, timeout=5
                    )
                    if "Docker Desktop.exe" not in result.stdout:
                        logger.error(f"Docker Desktop process {pid} not found in tasklist immediately after start")
                        return False, pid, "Docker Desktop process terminated immediately"
                except Exception as e:
                    logger.warning(f"Could not verify Docker Desktop process: {e}")

            # Wait for daemon readiness
            return self._wait_for_daemon(pid), pid, None

        except Exception as e:
            error_msg = f"Failed to start Docker Desktop: {e}"
            logger.error(error_msg)
            return False, None, error_msg

    def _wait_for_daemon(self, pid: int) -> bool:
        """Wait for Docker daemon to become responsive."""
        start_time = time.time()
        timeout = self.config.docker_startup_timeout
        interval = self.config.docker_startup_interval

        logger.info(f"Waiting for Docker daemon (timeout: {timeout}s, interval: {interval}s)...")

        while time.time() - start_time < timeout:
            if self.is_daemon_running():
                logger.info("Docker daemon is ready")
                return True

            # Check if Docker Desktop process is still alive
            try:
                if platform.system() == "Windows":
                    result = subprocess.run(
                        ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV"],
                        capture_output=True,
                        text=True,
                        timeout=5
                    )
                    if "Docker Desktop.exe" not in result.stdout:
                        logger.error("Docker Desktop process terminated unexpectedly")
                        return False
                else:
                    # On Unix, check if process exists
                    os.kill(pid, 0)
            except Exception:
                # Process may have exited
                logger.error("Docker Desktop process not found")
                return False

            if self.config.verbose:
                elapsed = int(time.time() - start_time)
                logger.debug(f"Waiting for Docker daemon... ({elapsed}s elapsed)")

            time.sleep(interval)

        logger.error(f"Timeout waiting for Docker daemon after {timeout}s")
        return False


class OllamaDetector:
    """Detect and manage Ollama lifecycle."""

    def __init__(self, config: StartupConfig, memora_config: MemoraConfig):
        self.config = config
        self.memora_config = memora_config
        self._ollama_process: Optional[subprocess.Popen] = None

    def is_ollama_installed(self) -> bool:
        """Check if Ollama is installed and available in PATH."""
        return shutil.which(self.config.ollama_executable) is not None

    def get_ollama_version(self) -> Optional[str]:
        """Get Ollama version if available."""
        try:
            result = subprocess.run(
                [self.config.ollama_executable, "--version"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception:
            pass
        return None

    def is_ollama_running(self, host: Optional[str] = None) -> bool:
        """Check if Ollama API is responding at the given host."""
        target_host = host or self.memora_config.ollama_host
        try:
            response = httpx.get(f"{target_host}/api/tags", timeout=5.0)
            return response.status_code == 200
        except Exception:
            return False

    def is_model_available(self, host: Optional[str] = None) -> bool:
        """Check if the configured embedding model is available."""
        target_host = host or self.memora_config.ollama_host
        try:
            response = httpx.get(f"{target_host}/api/tags", timeout=5.0)
            if response.status_code == 200:
                models = response.json().get("models", [])
                model_names = [m.get("name", "") for m in models]
                return any(self.memora_config.embedding_model in m for m in model_names)
        except Exception:
            pass
        return False

    def get_available_models(self, host: Optional[str] = None) -> List[str]:
        """Get list of available models."""
        target_host = host or self.memora_config.ollama_host
        try:
            response = httpx.get(f"{target_host}/api/tags", timeout=5.0)
            if response.status_code == 200:
                models = response.json().get("models", [])
                return [m.get("name", "") for m in models]
        except Exception:
            pass
        return []

    def start_ollama_serve(self) -> Tuple[bool, Optional[int], Optional[str]]:
        """
        Start Ollama serve as background process and wait for API readiness.

        Returns:
            Tuple of (success, process_id, error_message)
        """
        if not self.is_ollama_installed():
            return False, None, "Ollama not installed"

        # Check if already running
        if self.is_ollama_running():
            logger.info("Ollama already running")
            return True, None, None

        ollama_exe = self.config.ollama_executable
        logger.info(f"Starting Ollama serve from: {ollama_exe}")
        logger.debug(f"Platform: {platform.system()}, Command: [{ollama_exe}, serve]")

        try:
            # Start ollama serve as background process
            if platform.system() == "Windows":
                creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP
                self._ollama_process = subprocess.Popen(
                    [ollama_exe, "serve"],
                    creationflags=creation_flags,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            else:
                self._ollama_process = subprocess.Popen(
                    [ollama_exe, "serve"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )

            pid = self._ollama_process.pid
            logger.info(f"Ollama serve process started with PID: {pid}")

            # Verify process is alive
            time.sleep(1)
            if self._ollama_process.poll() is not None:
                logger.error(f"Ollama process {pid} terminated immediately")
                return False, pid, "Ollama process terminated immediately"

            # Wait for API readiness
            return self._wait_for_api(pid), pid, None

        except Exception as e:
            error_msg = f"Failed to start Ollama serve: {e}"
            logger.error(error_msg)
            return False, None, error_msg

    def _wait_for_api(self, pid: int) -> bool:
        """Wait for Ollama API to become responsive."""
        start_time = time.time()
        timeout = self.config.ollama_startup_timeout
        interval = self.config.ollama_startup_interval

        logger.info(f"Waiting for Ollama API (timeout: {timeout}s, interval: {interval}s)...")

        while time.time() - start_time < timeout:
            if self.is_ollama_running():
                logger.info("Ollama API is ready")
                # Also verify model is available
                if self.is_model_available():
                    logger.info(f"Required model '{self.memora_config.embedding_model}' is available")
                else:
                    logger.warning(f"Required model '{self.memora_config.embedding_model}' not yet available")
                return True

            # Check if process is still alive
            try:
                if self._ollama_process:
                    returncode = self._ollama_process.poll()
                    if returncode is not None:
                        logger.error(f"Ollama process terminated with code: {returncode}")
                        return False
            except Exception:
                logger.error("Ollama process not found")
                return False

            if self.config.verbose:
                elapsed = int(time.time() - start_time)
                logger.debug(f"Waiting for Ollama API... ({elapsed}s elapsed)")

            time.sleep(interval)

        logger.error(f"Timeout waiting for Ollama API after {timeout}s")
        return False

    def stop_ollama_if_owned(self) -> bool:
        """Stop Ollama process if it was started by MEMORA."""
        if self._ollama_process:
            try:
                if platform.system() == "Windows":
                    # Use CTRL_BREAK_EVENT for process group
                    self._ollama_process.send_signal(signal.CTRL_BREAK_EVENT)
                else:
                    self._ollama_process.terminate()

                # Wait for graceful shutdown
                try:
                    self._ollama_process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self._ollama_process.kill()
                    self._ollama_process.wait()

                logger.info("Ollama process stopped")
                self._ollama_process = None
                return True
            except Exception as e:
                logger.error(f"Failed to stop Ollama process: {e}")
                return False
        return True  # Nothing to stop


class DependencyLifecycleManager:
    """
    Manages automatic dependency detection and startup for MEMORA.

    Handles:
    - Docker Desktop lifecycle (detect, start, verify daemon)
    - Ollama lifecycle (detect, start, verify API, check model)
    - Process ownership tracking
    - Configurable timeouts and error handling
    """

    def __init__(self, memora_config: MemoraConfig, startup_config: Optional[StartupConfig] = None, project_root: Optional[Path] = None):
        self.memora_config = memora_config
        self.startup_config = startup_config or StartupConfig()
        self.project_root = project_root

        self.docker_detector = DockerDesktopDetector(self.startup_config)
        self.ollama_detector = OllamaDetector(self.startup_config, memora_config)

        # Track processes started by MEMORA
        self._started_processes: Dict[DependencyType, int] = {}
        self._dependency_info: Dict[DependencyType, DependencyInfo] = {}

    def detect_dependencies(self) -> Dict[DependencyType, DependencyInfo]:
        """
        Detect all required dependencies and their current state.

        Returns:
            Dict mapping dependency type to DependencyInfo
        """
        self._dependency_info = {}

        logger.info("Detecting Docker dependencies...")
        docker_info = self._detect_docker()
        self._dependency_info[DependencyType.DOCKER_DESKTOP] = docker_info
        logger.info(f"Docker detection: installed={docker_info.installed}, state={docker_info.state.value}, daemon_running={docker_info.details.get('daemon_running')}, desktop_installed={docker_info.details.get('docker_desktop_installed')}")

        logger.info("Detecting Ollama dependencies...")
        ollama_info = self._detect_ollama()
        self._dependency_info[DependencyType.OLLAMA] = ollama_info
        logger.info(f"Ollama detection: installed={ollama_info.installed}, state={ollama_info.state.value}, api_running={ollama_info.details.get('api_running')}, model_available={ollama_info.details.get('model_available')}")

        return self._dependency_info

    def _detect_docker(self) -> DependencyInfo:
        """Detect Docker CLI and Docker Desktop status."""
        info = DependencyInfo(type=DependencyType.DOCKER_DESKTOP)

        # Check Docker CLI
        info.installed = self.docker_detector.is_docker_cli_available()
        if info.installed:
            info.version = self.docker_detector.get_docker_version()
            info.executable_path = shutil.which("docker")

        # Check Docker Desktop installation
        docker_desktop_path = self.docker_detector.find_docker_desktop()
        info.details["docker_desktop_installed"] = docker_desktop_path is not None
        info.details["docker_desktop_path"] = docker_desktop_path

        # Check daemon status
        daemon_running = self.docker_detector.is_daemon_running()
        info.details["daemon_running"] = daemon_running

        # Check Docker Desktop process
        desktop_running = self.docker_detector.is_docker_desktop_running()
        info.details["desktop_process_running"] = desktop_running

        # Determine state
        if not info.installed:
            info.state = DependencyState.NOT_INSTALLED
            info.error_message = "Docker CLI not found in PATH"
        elif not daemon_running:
            if desktop_running:
                info.state = DependencyState.STARTING
            else:
                info.state = DependencyState.STOPPED
        else:
            info.state = DependencyState.RUNNING

        return info

    def _detect_ollama(self) -> DependencyInfo:
        """Detect Ollama installation and running status."""
        info = DependencyInfo(type=DependencyType.OLLAMA)

        # Check Ollama installation
        info.installed = self.ollama_detector.is_ollama_installed()
        if info.installed:
            info.version = self.ollama_detector.get_ollama_version()
            info.executable_path = shutil.which(self.startup_config.ollama_executable)

        # Check API status
        api_running = self.ollama_detector.is_ollama_running()
        info.details["api_running"] = api_running

        # Check model availability
        model_available = self.ollama_detector.is_model_available()
        info.details["model_available"] = model_available
        info.details["required_model"] = self.memora_config.embedding_model
        info.details["available_models"] = self.ollama_detector.get_available_models()

        # Determine state
        if not info.installed:
            info.state = DependencyState.NOT_INSTALLED
            info.error_message = "Ollama not installed"
        elif not api_running:
            info.state = DependencyState.STOPPED
        elif not model_available:
            info.state = DependencyState.RUNNING  # Running but model missing
            info.error_message = f"Model '{self.memora_config.embedding_model}' not available"
        else:
            info.state = DependencyState.RUNNING

        return info

    def start_missing_dependencies(self) -> Tuple[bool, List[str]]:
        """
        Start any missing dependencies that are installed but not running.

        Returns:
            Tuple of (overall_success, list_of_errors)
        """
        errors = []
        success = True

        # Start Docker Desktop if needed
        docker_info = self._dependency_info.get(DependencyType.DOCKER_DESKTOP)
        if docker_info and docker_info.installed and docker_info.state != DependencyState.RUNNING:
            if docker_info.state == DependencyState.NOT_INSTALLED:
                errors.append("Docker Desktop not installed")
                success = False
            else:
                logger.info(f"Starting Docker Desktop (current state: {docker_info.state.value})...")
                started, pid, error = self.docker_detector.start_docker_desktop()
                if started:
                    self._started_processes[DependencyType.DOCKER_DESKTOP] = pid or 0
                    docker_info.started_by_memora = True
                    docker_info.process_id = pid
                    docker_info.state = DependencyState.RUNNING
                    logger.info("Docker Desktop started successfully")
                else:
                    docker_info.state = DependencyState.FAILED
                    docker_info.error_message = error
                    errors.append(f"Docker Desktop: {error}")
                    success = False

        # Start Ollama if needed (host mode only)
        ollama_info = self._dependency_info.get(DependencyType.OLLAMA)
        if self.memora_config.ollama_mode == "host":
            if ollama_info and ollama_info.installed and ollama_info.state != DependencyState.RUNNING:
                if ollama_info.state == DependencyState.NOT_INSTALLED:
                    errors.append("Ollama not installed")
                    success = False
                else:
                    logger.info(f"Starting Ollama (current state: {ollama_info.state.value})...")
                    started, pid, error = self.ollama_detector.start_ollama_serve()
                    if started:
                        self._started_processes[DependencyType.OLLAMA] = pid or 0
                        ollama_info.started_by_memora = True
                        ollama_info.process_id = pid
                        ollama_info.state = DependencyState.RUNNING
                        logger.info("Ollama started successfully")
                    else:
                        ollama_info.state = DependencyState.FAILED
                        ollama_info.error_message = error
                        errors.append(f"Ollama: {error}")
                        success = False
        else:
            # Container mode - Ollama managed by Docker Compose
            logger.info("Ollama in container mode - managed by Docker Compose")
            if ollama_info:
                ollama_info.details["managed_by"] = "docker_compose"

        return success, errors

    def verify_dependencies_ready(self) -> Tuple[bool, List[str]]:
        """
        Verify all dependencies are ready for MEMORA operation.

        Returns:
            Tuple of (all_ready, list_of_issues)
        """
        issues = []
        all_ready = True

        # Verify Docker daemon
        if not self.docker_detector.is_daemon_running():
            issues.append("Docker daemon not responsive")
            all_ready = False
        else:
            logger.info("Docker daemon verified ready")

            # Additional verification: docker compose config works with project's .env.docker
            if self.project_root:
                try:
                    # Get the profiles based on ollama mode
                    profiles = ["http"]
                    if self.memora_config.ollama_mode == "container":
                        profiles.append("ollama")

                    result = subprocess.run(
                        ["docker", "compose", "--env-file", ".env.docker", "--profile", ",".join(profiles), "config"],
                        cwd=self.project_root,
                        capture_output=True, text=True, timeout=15
                    )
                    if result.returncode != 0:
                        issues.append(f"Docker Compose config validation failed: {result.stderr.strip()}")
                        all_ready = False
                    else:
                        logger.info("Docker Compose configuration verified")
                except Exception as e:
                    logger.warning(f"Could not verify Docker Compose config: {e}")

        # Verify Ollama (host mode)
        if self.memora_config.ollama_mode == "host":
            if not self.ollama_detector.is_ollama_running():
                issues.append("Ollama API not responding")
                all_ready = False
            elif not self.ollama_detector.is_model_available():
                issues.append(f"Required model '{self.memora_config.embedding_model}' not available in Ollama")
                # Don't fail - just warn
                logger.warning(f"Model '{self.memora_config.embedding_model}' not found in Ollama")
            else:
                logger.info("Ollama verified ready with required model")
        else:
            logger.info("Ollama in container mode - will be verified by Docker Compose health checks")

        return all_ready, issues

    def get_startup_report(self) -> Dict[str, Any]:
        """Generate a startup report for logging/output."""
        return {
            "docker": {
                "installed": self._dependency_info.get(DependencyType.DOCKER_DESKTOP, DependencyInfo(DependencyType.DOCKER_DESKTOP)).installed,
                "state": self._dependency_info.get(DependencyType.DOCKER_DESKTOP, DependencyInfo(DependencyType.DOCKER_DESKTOP)).state.value,
                "started_by_memora": self._dependency_info.get(DependencyType.DOCKER_DESKTOP, DependencyInfo(DependencyType.DOCKER_DESKTOP)).started_by_memora,
                "version": self._dependency_info.get(DependencyType.DOCKER_DESKTOP, DependencyInfo(DependencyType.DOCKER_DESKTOP)).version,
            },
            "ollama": {
                "installed": self._dependency_info.get(DependencyType.OLLAMA, DependencyInfo(DependencyType.OLLAMA)).installed,
                "state": self._dependency_info.get(DependencyType.OLLAMA, DependencyInfo(DependencyType.OLLAMA)).state.value,
                "started_by_memora": self._dependency_info.get(DependencyType.OLLAMA, DependencyInfo(DependencyType.OLLAMA)).started_by_memora,
                "version": self._dependency_info.get(DependencyType.OLLAMA, DependencyInfo(DependencyType.OLLAMA)).version,
                "model_available": self._dependency_info.get(DependencyType.OLLAMA, DependencyInfo(DependencyType.OLLAMA)).details.get("model_available", False),
                "required_model": self.memora_config.embedding_model,
                "mode": self.memora_config.ollama_mode,
            },
            "started_processes": {k.value: v for k, v in self._started_processes.items()},
        }

    def cleanup_owned_processes(self) -> bool:
        """
        Clean up processes started by MEMORA.

        Returns:
            True if all owned processes stopped successfully
        """
        success = True

        # Stop Ollama if we started it
        ollama_info = self._dependency_info.get(DependencyType.OLLAMA)
        if ollama_info and ollama_info.started_by_memora:
            logger.info("Stopping MEMORA-owned Ollama process...")
            if not self.ollama_detector.stop_ollama_if_owned():
                success = False

        # Note: We do NOT stop Docker Desktop as it's a user application
        # Docker Desktop shutdown should be explicit and user-initiated

        return success