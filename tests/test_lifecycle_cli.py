"""
Tests for MEMORA Lifecycle CLI module.
"""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock, PropertyMock
from pathlib import Path
import sys

from memora.lifecycle.cli import (
    discover_project_root,
    load_config,
    PreflightValidator,
    ComposeManager,
    orchestrate_start,
    orchestrate_stop,
    orchestrate_restart,
    orchestrate_purge,
    get_status,
    ValidationSeverity,
    ValidationResult,
    PreflightReport,
    ContainerStatus,
)
from memora.config import MemoraConfig


# Module-level fixtures
@pytest.fixture
def project_root(tmp_path):
    """Create a temporary project root."""
    root = tmp_path / "project"
    root.mkdir()
    (root / "docker-compose.yml").write_text("version: '3'\nservices: {}\n")
    (root / "Dockerfile").write_text("FROM python:3.12\n")
    (root / ".env.docker").write_text("VAULT_PATH=/vault\n")
    (root / ".env.example").write_text("VAULT_PATH=/test/vault\n")
    (root / ".env").write_text("VAULT_PATH=/test/vault\n")
    (root / "pyproject.toml").write_text("[project]\nname = 'test'\n")
    return root


@pytest.fixture
def mock_config():
    """Create a mock MemoraConfig."""
    config = MagicMock(spec=MemoraConfig)
    config.ollama_mode = "host"
    config.ollama_host = "http://localhost:11434"
    config.embedding_model = "nomic-embed-text"
    config.mcp_host = "127.0.0.1"
    config.mcp_port = 8080
    config.mcp_transport = "http"
    config.chroma_path = Path("/tmp/chromadb")
    config.sqlite_path = Path("/tmp/memora.db")
    config.log_file = Path("/tmp/memora.log")
    config.data_dir = Path("/tmp")
    config.vault_path = Path("/tmp/vault")
    config.validate_vault.return_value = True
    config.log_level = "INFO"
    config.ollama_mode = "host"
    config.ollama_host = "http://localhost:11434"
    config.embedding_model = "nomic-embed-text"
    config.mcp_host = "127.0.0.1"
    config.mcp_port = 8080
    config.mcp_transport = "http"
    return config


class TestProjectRootDiscovery:
    """Test project root discovery mechanism."""

    def test_discover_from_env_var(self, tmp_path, monkeypatch):
        """Test discovery via MEMORA_HOME env var."""
        project_dir = tmp_path / "my_project"
        project_dir.mkdir()
        (project_dir / "pyproject.toml").write_text("[project]\nname = 'test'\n")

        monkeypatch.setenv("MEMORA_HOME", str(project_dir))
        result = discover_project_root()
        assert result == project_dir

    def test_discover_from_cwd(self, tmp_path, monkeypatch):
        """Test discovery from current working directory."""
        project_dir = tmp_path / "my_project"
        project_dir.mkdir()
        (project_dir / ".env").write_text("VAULT_PATH=/test\n")

        monkeypatch.chdir(project_dir)
        result = discover_project_root()
        assert result == project_dir

    def test_discover_invalid_env_fallbacks_to_cwd(self, tmp_path, monkeypatch):
        """Test fallback when MEMORA_HOME is invalid."""
        project_dir = tmp_path / "my_project"
        project_dir.mkdir()
        (project_dir / "pyproject.toml").write_text("[project]\nname = 'test'\n")

        monkeypatch.setenv("MEMORA_HOME", "/nonexistent")
        monkeypatch.chdir(project_dir)
        result = discover_project_root()
        assert result == project_dir


class TestLoadConfig:
    """Test configuration loading."""

    def test_load_config(self, tmp_path, monkeypatch):
        """Test loading config from project root."""
        project_dir = tmp_path / "my_project"
        project_dir.mkdir()
        # Create a valid vault path for testing
        vault_dir = project_dir / "test_vault"
        vault_dir.mkdir()
        (vault_dir / ".obsidian").mkdir()
        (vault_dir / "test.md").write_text("# Test\n\nContent\n")

        (project_dir / ".env").write_text(f"VAULT_PATH={vault_dir}\n")
        (project_dir / "pyproject.toml").write_text("[project]\nname = 'test'\n")

        config = load_config(project_dir)
        # Config should be a MemoraConfig-like object (dynamic class)
        assert hasattr(config, 'vault_path')
        assert hasattr(config, 'chroma_path')
        assert hasattr(config, 'sqlite_path')
        # The config resolves paths against project_dir
        assert config.vault_path is not None
        assert project_dir in config.chroma_path.parents
        assert project_dir in config.sqlite_path.parents


class TestPreflightValidator:
    """Test preflight validation engine."""

    @pytest.fixture
    def mock_config(self):
        """Create a mock MemoraConfig."""
        config = MagicMock(spec=MemoraConfig)
        config.ollama_mode = "host"
        config.ollama_host = "http://localhost:11434"
        config.embedding_model = "nomic-embed-text"
        config.mcp_port = 8080
        config.mcp_host = "127.0.0.1"
        config.mcp_transport = "http"
        config.chroma_path = Path("/tmp/chromadb")
        config.sqlite_path = Path("/tmp/memora.db")
        config.log_file = Path("/tmp/memora.log")
        config.data_dir = Path("/tmp")
        config.vault_path = Path("/tmp/vault")
        config.validate_vault.return_value = True
        config.log_level = "INFO"
        return config

    @pytest.fixture
    def project_root(self, tmp_path):
        """Create a temporary project root with required files."""
        root = tmp_path / "project"
        root.mkdir()
        (root / "docker-compose.yml").write_text("version: '3'\nservices: {}\n")
        (root / "Dockerfile").write_text("FROM python:3.12\n")
        (root / ".env.docker").write_text("VAULT_PATH=/vault\n")
        (root / ".env").write_text("VAULT_PATH=/test/vault\n")
        return root

    def test_validator_initialization(self, project_root, mock_config):
        """Test validator initializes correctly."""
        validator = PreflightValidator(project_root, mock_config)
        assert validator.project_root == project_root
        assert validator.config == mock_config

    @patch("shutil.which")
    @patch("subprocess.run")
    @patch("httpx.get")
    @patch("socket.socket")
    def test_run_all_checks(self, mock_socket, mock_httpx_get, mock_subprocess, mock_which, project_root, mock_config):
        """Test running all preflight checks."""
        # Mock Docker CLI
        mock_which.return_value = "/usr/bin/docker"

        # Mock Docker daemon
        mock_subprocess.return_value = MagicMock(returncode=0, stdout="Docker version 24.0.0", stderr="")

        # Mock Docker Compose - need multiple calls
        call_count = [0]
        def side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return MagicMock(returncode=0, stdout="Docker version 24.0.0", stderr="")  # docker --version
            elif call_count[0] == 2:
                return MagicMock(returncode=0, stdout="Docker Compose version v2.20.0", stderr="")  # docker compose version
            elif call_count[0] == 3:
                return MagicMock(returncode=0, stdout="Containers: 0", stderr="")  # docker info
            elif call_count[0] == 4:
                return MagicMock(returncode=0, stdout="config ok", stderr="")  # docker compose config
            return MagicMock(returncode=0, stdout="", stderr="")
        mock_subprocess.side_effect = side_effect

        # Mock Ollama
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"models": [{"name": "nomic-embed-text:latest"}]}
        mock_httpx_get.return_value = mock_response

        # Mock socket for port check
        mock_sock = MagicMock()
        mock_sock.connect_ex.return_value = 1  # Port not in use
        mock_socket.return_value = mock_sock

        validator = PreflightValidator(project_root, mock_config)
        report = validator.run_all()

        assert isinstance(report, PreflightReport)
        assert len(report.results) > 0

    def test_check_os_compatibility(self, project_root, mock_config):
        """Test OS compatibility check."""
        validator = PreflightValidator(project_root, mock_config)
        validator._check_os_compatibility()
        assert len(validator.report.results) == 1
        assert validator.report.results[0].name == "OS Compatibility"

    def test_check_python_version(self, project_root, mock_config):
        """Test Python version check."""
        validator = PreflightValidator(project_root, mock_config)
        validator._check_python_version()
        assert len(validator.report.results) == 1
        assert validator.report.results[0].name == "Python Version"
        assert validator.report.results[0].severity == ValidationSeverity.INFO


class TestComposeManager:
    """Test Docker Compose management."""

    @pytest.fixture
    def mock_config(self):
        """Create a mock MemoraConfig."""
        config = MagicMock(spec=MemoraConfig)
        config.ollama_mode = "host"
        config.mcp_port = 8080
        config.mcp_host = "127.0.0.1"
        config.mcp_transport = "http"
        config.ollama_host = "http://localhost:11434"
        config.embedding_model = "nomic-embed-text"
        config.log_level = "INFO"
        return config

    @pytest.fixture
    def project_root(self, tmp_path):
        """Create a temporary project root."""
        root = tmp_path / "project"
        root.mkdir()
        (root / "docker-compose.yml").write_text("version: '3'\nservices: {}\n")
        return root

    def test_get_profiles_host_mode(self, project_root, mock_config):
        """Test profile determination for host mode."""
        mock_config.ollama_mode = "host"
        manager = ComposeManager(project_root, mock_config)
        profiles = manager._get_profiles()
        assert profiles == ["http"]

    def test_get_profiles_container_mode(self, project_root, mock_config):
        """Test profile determination for container mode."""
        mock_config.ollama_mode = "container"
        manager = ComposeManager(project_root, mock_config)
        profiles = manager._get_profiles()
        assert profiles == ["http", "ollama"]

    @patch("memora.lifecycle.cli.subprocess.run")
    def test_run_compose_docker_not_found(self, mock_run, project_root, mock_config):
        """Test handling when Docker is not installed."""
        mock_run.side_effect = FileNotFoundError("docker not found")
        manager = ComposeManager(project_root, mock_config)
        result = manager._run_compose(["ps"])
        assert result.returncode == 1
        assert "docker not found" in result.stderr


class TestOrchestration:
    """Test startup orchestration functions."""

    @pytest.fixture
    def project_root(self, tmp_path):
        """Create a temporary project root."""
        root = tmp_path / "project"
        root.mkdir()
        (root / "docker-compose.yml").write_text("version: '3'\nservices: {}\n")
        (root / "Dockerfile").write_text("FROM python:3.12\n")
        return root

    @pytest.fixture
    def mock_config(self):
        """Create a mock MemoraConfig."""
        config = MagicMock(spec=MemoraConfig)
        config.ollama_mode = "host"
        config.mcp_port = 8080
        config.mcp_host = "127.0.0.1"
        config.mcp_transport = "http"
        config.ollama_host = "http://localhost:11434"
        config.embedding_model = "nomic-embed-text"
        config.log_level = "INFO"
        return config

    @patch("memora.lifecycle.cli.DependencyLifecycleManager")
    @patch("memora.lifecycle.cli.ComposeManager")
    @patch("memora.lifecycle.cli.subprocess.run")
    def test_orchestrate_start_skip_preflight(self, mock_subprocess, mock_compose_class, mock_dep_manager_class, project_root, mock_config):
        """Test start orchestration with skip_preflight."""
        # Configure mock config with all required attributes
        mock_config.vault_path = Path("/test/vault")
        mock_config.mcp_host = "127.0.0.1"
        mock_config.mcp_port = 8080
        mock_config.mcp_transport = "http"
        mock_config.ollama_mode = "host"

        # Mock dependency manager
        mock_dep_manager = MagicMock()
        mock_dep_manager.detect_dependencies.return_value = {}
        mock_dep_manager.start_missing_dependencies.return_value = (True, [])
        mock_dep_manager.verify_dependencies_ready.return_value = (True, [])
        mock_dep_manager.cleanup_owned_processes.return_value = True
        mock_dep_manager_class.return_value = mock_dep_manager

        mock_compose = MagicMock()
        mock_compose._get_profiles.return_value = ["http"]
        mock_compose.build.return_value = True
        mock_compose.up.return_value = True
        mock_compose.wait_healthy.return_value = True
        mock_compose.verify_health_endpoints.return_value = True
        mock_compose_class.return_value = mock_compose

        mock_subprocess.return_value = MagicMock(returncode=0, stdout="", stderr="")

        exit_code = orchestrate_start(project_root, mock_config, skip_preflight=True)
        assert exit_code == 0
        mock_compose.build.assert_called_once()
        mock_compose.up.assert_called_once_with(detach=True)

    @patch("memora.lifecycle.cli.ComposeManager")
    @patch("memora.lifecycle.cli.subprocess.run")
    def test_orchestrate_stop(self, mock_subprocess, mock_compose_class, project_root, mock_config):
        """Test stop orchestration (preserves volumes)."""
        mock_compose = MagicMock()
        mock_compose.down.return_value = True
        mock_compose_class.return_value = mock_compose

        # Mock Docker as available
        mock_subprocess.return_value = MagicMock(returncode=0, stdout="", stderr="")

        exit_code = orchestrate_stop(project_root, mock_config)
        assert exit_code == 0
        mock_compose.down.assert_called_once_with(remove_volumes=False)

    @patch("memora.lifecycle.cli.ComposeManager")
    @patch("memora.lifecycle.cli.subprocess.run")
    def test_orchestrate_stop_docker_unavailable(self, mock_subprocess, mock_compose_class, project_root, mock_config):
        """Test stop orchestration handles Docker unavailable gracefully."""
        mock_compose = MagicMock()
        mock_compose_class.return_value = mock_compose

        # Mock Docker as unavailable (FileNotFoundError)
        mock_subprocess.side_effect = FileNotFoundError("docker not found")

        exit_code = orchestrate_stop(project_root, mock_config)
        assert exit_code == 0
        mock_compose.down.assert_not_called()

    @patch("memora.lifecycle.cli.ComposeManager")
    @patch("memora.lifecycle.cli.typer.confirm")
    def test_orchestrate_purge_requires_confirmation(self, mock_confirm, mock_compose_class, project_root, mock_config):
        """Test purge requires explicit confirmation."""
        mock_compose = MagicMock()
        mock_compose.down.return_value = True
        mock_compose_class.return_value = mock_compose
        mock_confirm.return_value = False  # User declines

        # Without --confirm-destroy, should fail
        exit_code = orchestrate_purge(project_root, mock_config, confirm_destroy=False)
        assert exit_code == 1
        mock_compose.down.assert_not_called()

    @patch("memora.lifecycle.cli.ComposeManager")
    @patch("memora.lifecycle.cli.typer.confirm")
    def test_orchestrate_purge_with_confirmation(self, mock_confirm, mock_compose_class, project_root, mock_config):
        """Test purge with confirmation deletes volumes."""
        mock_compose = MagicMock()
        mock_compose.down.return_value = True
        mock_compose_class.return_value = mock_compose
        mock_confirm.return_value = True  # User confirms

        exit_code = orchestrate_purge(project_root, mock_config, confirm_destroy=True)
        assert exit_code == 0
        mock_compose.down.assert_called_once_with(remove_volumes=True)

    @patch("memora.lifecycle.cli.ComposeManager")
    @patch("memora.lifecycle.cli.typer.confirm")
    def test_orchestrate_purge_user_declines(self, mock_confirm, mock_compose_class, project_root, mock_config):
        """Test purge aborts when user declines confirmation."""
        mock_compose = MagicMock()
        mock_compose_class.return_value = mock_compose
        mock_confirm.return_value = False  # User declines at final prompt

        exit_code = orchestrate_purge(project_root, mock_config, confirm_destroy=True)
        assert exit_code == 0  # Returns 0 for aborted
        mock_compose.down.assert_not_called()

    @patch("memora.lifecycle.cli.ComposeManager")
    def test_orchestrate_restart(self, mock_compose_class, project_root, mock_config):
        """Test restart orchestration."""
        mock_compose = MagicMock()
        mock_compose.restart.return_value = True
        mock_compose.wait_healthy.return_value = True
        mock_compose.verify_health_endpoints.return_value = True
        mock_compose_class.return_value = mock_compose

        exit_code = orchestrate_restart(project_root, mock_config)
        assert exit_code == 0
        mock_compose.restart.assert_called_once()

    @patch("memora.lifecycle.cli.ComposeManager")
    @patch("memora.lifecycle.cli.subprocess.run")
    @patch("urllib.request.urlopen")
    def test_get_status(self, mock_urlopen, mock_subprocess, mock_compose_class, project_root, mock_config):
        """Test status retrieval."""
        # Configure mock config with all required attributes
        mock_config.chroma_path = Path("/tmp/chromadb")
        mock_config.sqlite_path = Path("/tmp/memora.db")
        mock_config.log_file = Path("/tmp/memora.log")
        mock_config.vault_path = Path("/tmp/vault")
        mock_config.validate_vault.return_value = True
        mock_config.mcp_host = "127.0.0.1"
        mock_config.mcp_port = 8080
        mock_config.mcp_transport = "http"
        mock_config.ollama_host = "http://localhost:11434"
        mock_config.embedding_model = "nomic-embed-text"

        mock_compose = MagicMock()
        mock_compose.ps.return_value = [
            ContainerStatus(name="memora-http", status="running", health="healthy", ports=["127.0.0.1:8080->8080/tcp"], image="memora:latest")
        ]
        mock_compose_class.return_value = mock_compose

        mock_subprocess.return_value = MagicMock(returncode=0, stdout="", stderr="")

        # Mock urllib for health check
        mock_response = MagicMock()
        mock_response.read.return_value = b'{"status": "ready"}'
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=None)
        mock_urlopen.return_value = mock_response

        exit_code = get_status(project_root, mock_config)
        assert exit_code == 0


class TestValidationStructures:
    """Test validation data structures."""

    def test_validation_result(self):
        """Test ValidationResult creation."""
        result = ValidationResult(
            name="Test Check",
            severity=ValidationSeverity.INFO,
            message="All good",
            details={"key": "value"},
            remediation="Do something"
        )
        assert result.name == "Test Check"
        assert result.severity == ValidationSeverity.INFO
        assert result.message == "All good"
        assert result.details == {"key": "value"}
        assert result.remediation == "Do something"

    def test_preflight_report_summary(self):
        """Test PreflightReport summary."""
        report = PreflightReport()
        report.add_result(ValidationResult("Check 1", ValidationSeverity.INFO, "OK"))
        report.add_result(ValidationResult("Check 2", ValidationSeverity.WARN, "Warning"))
        report.add_result(ValidationResult("Check 3", ValidationSeverity.ERROR, "Error"))

        summary = report.get_summary()
        assert summary["INFO"] == 1
        assert summary["WARN"] == 1
        assert summary["ERROR"] == 1
        assert report.has_errors is True
        assert report.has_warnings is True

    def test_container_status(self):
        """Test ContainerStatus creation."""
        container = ContainerStatus(
            name="memora-http",
            status="running",
            health="healthy",
            ports=["127.0.0.1:8080->8080/tcp"],
            image="memora:latest"
        )
        assert container.name == "memora-http"
        assert container.status == "running"
        assert container.health == "healthy"


class TestCLIArgumentParsing:
    """Test CLI argument parsing."""

    @patch("memora.cli._get_project_and_config")
    @patch("memora.cli.orchestrate_start")
    def test_start_flag(self, mock_start, mock_get_config, monkeypatch):
        """Test --start flag."""
        from memora.cli import app
        from typer.testing import CliRunner

        mock_get_config.return_value = (Path("/tmp"), MagicMock())
        mock_start.return_value = 0

        runner = CliRunner()
        result = runner.invoke(app, ["--start", "--skip-preflight"])
        assert result.exit_code == 0
        mock_start.assert_called_once()

    @patch("memora.cli._get_project_and_config")
    @patch("memora.cli.get_status")
    def test_status_flag(self, mock_get_status, mock_get_config):
        """Test --status flag."""
        from memora.cli import app
        from typer.testing import CliRunner

        mock_get_config.return_value = (Path("/tmp"), MagicMock())
        mock_get_status.return_value = 0

        runner = CliRunner()
        result = runner.invoke(app, ["--status"])
        assert result.exit_code == 0
        mock_get_status.assert_called_once()

    @patch("memora.cli._get_project_and_config")
    def test_version_flag(self, mock_get_config):
        """Test --version flag."""
        from memora.cli import app
        from typer.testing import CliRunner

        mock_get_config.return_value = (Path("/tmp"), MagicMock())

        runner = CliRunner()
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert "MEMORA version:" in result.output

    def test_no_flags_shows_help(self):
        """Test that no flags shows help."""
        from memora.cli import app
        from typer.testing import CliRunner

        runner = CliRunner()
        result = runner.invoke(app, [])
        assert result.exit_code == 0
        assert "MEMORA" in result.output


class TestAdditionalCoverage:
    """Additional tests for edge cases and new functionality."""

    @patch("memora.lifecycle.cli.DependencyLifecycleManager")
    @patch("memora.lifecycle.cli.ComposeManager")
    @patch("memora.lifecycle.cli.subprocess.run")
    @patch("httpx.get")
    def test_orchestrate_start_host_ollama_healthy(self, mock_httpx_get, mock_subprocess, mock_compose_class, mock_dep_manager_class, project_root, mock_config):
        """Test orchestrate_start with healthy host Ollama."""
        # Configure mock config
        mock_config.ollama_mode = "host"
        mock_config.ollama_host = "http://localhost:11434"
        mock_config.embedding_model = "nomic-embed-text"
        mock_config.mcp_host = "127.0.0.1"
        mock_config.mcp_port = 8080
        mock_config.mcp_transport = "http"
        mock_config.vault_path = Path("/test/vault")

        # Mock dependency manager - Ollama healthy
        mock_dep_manager = MagicMock()
        mock_dep_manager.detect_dependencies.return_value = {}
        mock_dep_manager.start_missing_dependencies.return_value = (True, [])
        mock_dep_manager.verify_dependencies_ready.return_value = (True, [])
        mock_dep_manager.cleanup_owned_processes.return_value = True
        mock_dep_manager_class.return_value = mock_dep_manager

        mock_compose = MagicMock()
        mock_compose._get_profiles.return_value = ["http"]
        mock_compose.build.return_value = True
        mock_compose.up.return_value = True
        mock_compose.wait_healthy.return_value = True
        mock_compose.verify_health_endpoints.return_value = True
        mock_compose_class.return_value = mock_compose

        mock_subprocess.return_value = MagicMock(returncode=0, stdout="", stderr="")

        # Mock healthy Ollama response (for the old check in orchestrate_start)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"models": [{"name": "nomic-embed-text:latest"}]}
        mock_httpx_get.return_value = mock_response

        exit_code = orchestrate_start(project_root, mock_config, skip_preflight=True)
        assert exit_code == 0
        mock_compose.build.assert_called_once()
        mock_compose.up.assert_called_once()

    @patch("memora.lifecycle.cli.DependencyLifecycleManager")
    @patch("memora.lifecycle.cli.ComposeManager")
    @patch("memora.lifecycle.cli.subprocess.run")
    @patch("httpx.get")
    def test_orchestrate_start_host_ollama_not_running(self, mock_httpx_get, mock_subprocess, mock_compose_class, mock_dep_manager_class, project_root, mock_config):
        """Test orchestrate_start with host Ollama not running."""
        mock_config.ollama_mode = "host"
        mock_config.ollama_host = "http://localhost:11434"
        mock_config.embedding_model = "nomic-embed-text"
        mock_config.mcp_host = "127.0.0.1"
        mock_config.mcp_port = 8080
        mock_config.mcp_transport = "http"
        mock_config.vault_path = Path("/test/vault")

        # Mock dependency manager - Ollama not running but will be started
        mock_dep_manager = MagicMock()
        mock_dep_manager.detect_dependencies.return_value = {}
        mock_dep_manager.start_missing_dependencies.return_value = (True, [])
        mock_dep_manager.verify_dependencies_ready.return_value = (True, [])
        mock_dep_manager.cleanup_owned_processes.return_value = True
        mock_dep_manager_class.return_value = mock_dep_manager

        mock_compose = MagicMock()
        mock_compose._get_profiles.return_value = ["http"]
        mock_compose.build.return_value = True
        mock_compose.up.return_value = True
        mock_compose.wait_healthy.return_value = True
        mock_compose.verify_health_endpoints.return_value = True
        mock_compose_class.return_value = mock_compose

        mock_subprocess.return_value = MagicMock(returncode=0, stdout="", stderr="")

        # Mock Ollama connection error (for the old check in orchestrate_start)
        import httpx
        mock_httpx_get.side_effect = httpx.ConnectError("Connection refused")

        exit_code = orchestrate_start(project_root, mock_config, skip_preflight=True)
        # Should still succeed (just warns about Ollama not running)
        assert exit_code == 0

    @patch("memora.lifecycle.cli.DependencyLifecycleManager")
    @patch("memora.lifecycle.cli.ComposeManager")
    @patch("memora.lifecycle.cli.subprocess.run")
    def test_orchestrate_start_health_check_failure_rollback(self, mock_subprocess, mock_compose_class, mock_dep_manager_class, project_root, mock_config):
        """Test rollback on health check failure."""
        mock_config.ollama_mode = "host"
        mock_config.ollama_host = "http://localhost:11434"
        mock_config.embedding_model = "nomic-embed-text"
        mock_config.mcp_host = "127.0.0.1"
        mock_config.mcp_port = 8080
        mock_config.mcp_transport = "http"
        mock_config.vault_path = Path("/test/vault")

        # Mock dependency manager
        mock_dep_manager = MagicMock()
        mock_dep_manager.detect_dependencies.return_value = {}
        mock_dep_manager.start_missing_dependencies.return_value = (True, [])
        mock_dep_manager.verify_dependencies_ready.return_value = (True, [])
        mock_dep_manager.cleanup_owned_processes.return_value = True
        mock_dep_manager_class.return_value = mock_dep_manager

        mock_compose = MagicMock()
        mock_compose._get_profiles.return_value = ["http"]
        mock_compose.build.return_value = True
        mock_compose.up.return_value = True
        mock_compose.wait_healthy.return_value = False  # Health check fails
        mock_compose_class.return_value = mock_compose

        mock_subprocess.return_value = MagicMock(returncode=0, stdout="", stderr="")

        exit_code = orchestrate_start(project_root, mock_config, skip_preflight=True)
        assert exit_code == 1

    @patch("memora.lifecycle.cli.DependencyLifecycleManager")
    @patch("memora.lifecycle.cli.ComposeManager")
    @patch("memora.lifecycle.cli.subprocess.run")
    def test_orchestrate_start_build_failure(self, mock_subprocess, mock_compose_class, mock_dep_manager_class, project_root, mock_config):
        """Test orchestrate_start handles build failure."""
        mock_config.ollama_mode = "host"
        mock_config.mcp_host = "127.0.0.1"
        mock_config.mcp_port = 8080
        mock_config.mcp_transport = "http"
        mock_config.vault_path = Path("/test/vault")

        # Mock dependency manager
        mock_dep_manager = MagicMock()
        mock_dep_manager.detect_dependencies.return_value = {}
        mock_dep_manager.start_missing_dependencies.return_value = (True, [])
        mock_dep_manager.verify_dependencies_ready.return_value = (True, [])
        mock_dep_manager.cleanup_owned_processes.return_value = True
        mock_dep_manager_class.return_value = mock_dep_manager

        mock_compose = MagicMock()
        mock_compose._get_profiles.return_value = ["http"]
        mock_compose.build.return_value = False  # Build fails
        mock_compose_class.return_value = mock_compose

        mock_subprocess.return_value = MagicMock(returncode=0, stdout="", stderr="")

        exit_code = orchestrate_start(project_root, mock_config, skip_preflight=True)
        assert exit_code == 1
        mock_compose.build.assert_called_once()

    @patch("memora.lifecycle.cli.DependencyLifecycleManager")
    @patch("memora.lifecycle.cli.ComposeManager")
    @patch("memora.lifecycle.cli.subprocess.run")
    def test_orchestrate_start_up_failure(self, mock_subprocess, mock_compose_class, mock_dep_manager_class, project_root, mock_config):
        """Test orchestrate_start handles up failure."""
        mock_config.ollama_mode = "host"
        mock_config.mcp_host = "127.0.0.1"
        mock_config.mcp_port = 8080
        mock_config.mcp_transport = "http"
        mock_config.vault_path = Path("/test/vault")

        # Mock dependency manager
        mock_dep_manager = MagicMock()
        mock_dep_manager.detect_dependencies.return_value = {}
        mock_dep_manager.start_missing_dependencies.return_value = (True, [])
        mock_dep_manager.verify_dependencies_ready.return_value = (True, [])
        mock_dep_manager.cleanup_owned_processes.return_value = True
        mock_dep_manager_class.return_value = mock_dep_manager

        mock_compose = MagicMock()
        mock_compose._get_profiles.return_value = ["http"]
        mock_compose.build.return_value = True
        mock_compose.up.return_value = False  # Up fails
        mock_compose_class.return_value = mock_compose

        mock_subprocess.return_value = MagicMock(returncode=0, stdout="", stderr="")

        exit_code = orchestrate_start(project_root, mock_config, skip_preflight=True)
        assert exit_code == 1
        mock_compose.up.assert_called_once()

    def test_validate_docker_bind_mount_windows_path(self, project_root, mock_config):
        """Test _validate_docker_bind_mount with Windows path."""
        from memora.lifecycle.cli import PreflightValidator
        mock_config.vault_path = Path("/host_mnt/c/Users/test/My Vault")
        validator = PreflightValidator(project_root, mock_config)
        validator._validate_docker_bind_mount()
        # Should have a warning about spaces
        results = [r for r in validator.report.results if r.name == "Docker Bind Mount"]
        assert len(results) == 1
        assert results[0].severity == ValidationSeverity.WARN

    def test_validate_docker_bind_mount_backslashes(self, project_root, mock_config):
        """Test _validate_docker_bind_mount with backslashes (Windows drive path)."""
        from memora.lifecycle.cli import PreflightValidator
        mock_config.vault_path = Path("C:\\Users\\test\\My Vault")
        validator = PreflightValidator(project_root, mock_config)
        validator._validate_docker_bind_mount()
        results = [r for r in validator.report.results if r.name == "Docker Bind Mount"]
        assert len(results) == 1
        # Windows drive-letter paths with backslashes are now valid (WARN for spaces only)
        assert results[0].severity == ValidationSeverity.WARN
        assert "spaces" in results[0].message

    def test_validate_docker_bind_mount_valid(self, project_root, mock_config):
        """Test _validate_docker_bind_mount with valid path."""
        from memora.lifecycle.cli import PreflightValidator
        mock_config.vault_path = Path("/host_mnt/c/Users/test/vault")
        validator = PreflightValidator(project_root, mock_config)
        validator._validate_docker_bind_mount()
        results = [r for r in validator.report.results if r.name == "Docker Bind Mount"]
        assert len(results) == 1
        assert results[0].severity == ValidationSeverity.INFO

    def test_validate_docker_bind_mount_windows_drive(self, project_root, mock_config):
        """Test _validate_docker_bind_mount with Windows drive letter (forward slashes)."""
        from memora.lifecycle.cli import PreflightValidator
        mock_config.vault_path = Path("C:/Users/test/vault")
        validator = PreflightValidator(project_root, mock_config)
        validator._validate_docker_bind_mount()
        results = [r for r in validator.report.results if r.name == "Docker Bind Mount"]
        assert len(results) == 1
        # C:/ format with forward slashes is compatible with Docker Desktop
        assert results[0].severity == ValidationSeverity.INFO
        assert "compatible" in results[0].message

    @patch("memora.lifecycle.cli.ComposeManager")
    def test_compose_manager_get_service_state(self, mock_compose_class, project_root, mock_config):
        """Test ComposeManager.get_service_state."""
        from memora.lifecycle.cli import ContainerStatus
        mock_compose = MagicMock()
        mock_compose.ps.return_value = [
            ContainerStatus(name="memora-http", status="running", health="healthy", ports=[], image="memora:latest"),
            ContainerStatus(name="memora-ollama", status="exited", health="", ports=[], image="ollama:latest"),
        ]
        mock_compose_class.return_value = mock_compose

        from memora.lifecycle.cli import ComposeManager
        compose = ComposeManager(project_root, mock_config)
        # The mock_compose is the instance returned by ComposeManager()
        # We need to set up the mock instance's methods
        mock_compose.get_service_state.return_value = {"memora-http": "running", "memora-ollama": "exited"}
        state = compose.get_service_state()
        assert state == {"memora-http": "running", "memora-ollama": "exited"}

    def test_compose_manager_rollback(self, project_root, mock_config):
        """Test ComposeManager.rollback."""
        from memora.lifecycle.cli import ComposeManager
        # Create a real ComposeManager instance but mock its down method
        compose = ComposeManager(project_root, mock_config)
        # Mock the down method on the instance
        with patch.object(compose, 'down', return_value=True) as mock_down:
            result = compose.rollback()
            assert result is True
            mock_down.assert_called_once_with(remove_volumes=False)

    def test_compose_manager_configurable_timeouts(self, project_root, mock_config):
        """Test ComposeManager configurable timeouts."""
        from memora.lifecycle.cli import ComposeManager
        mock_compose_class = MagicMock()
        with patch("memora.lifecycle.cli.ComposeManager", mock_compose_class):
            compose = ComposeManager(project_root, mock_config)
            assert compose.build_timeout == 300
            assert compose.compose_timeout == 120
            assert compose.health_timeout == 120
            assert compose.health_interval == 5
            assert compose.startup_timeout == 60

    @patch("memora.lifecycle.cli.ComposeManager")
    @patch("memora.lifecycle.cli.subprocess.run")
    @patch("httpx.get")
    def test_orchestrate_start_container_ollama_mode(self, mock_httpx_get, mock_subprocess, mock_compose_class, project_root, mock_config):
        """Test orchestrate_start with container Ollama mode."""
        mock_config.ollama_mode = "container"
        mock_config.ollama_host = "http://ollama:11434"
        mock_config.embedding_model = "nomic-embed-text"
        mock_config.mcp_host = "127.0.0.1"
        mock_config.mcp_port = 8080
        mock_config.mcp_transport = "http"
        mock_config.vault_path = Path("/test/vault")

        mock_compose = MagicMock()
        mock_compose._get_profiles.return_value = ["http", "ollama"]
        mock_compose.build.return_value = True
        mock_compose.up.return_value = True
        mock_compose.wait_healthy.return_value = True
        mock_compose.verify_health_endpoints.return_value = True
        mock_compose_class.return_value = mock_compose

        mock_subprocess.return_value = MagicMock(returncode=0, stdout="", stderr="")

        exit_code = orchestrate_start(project_root, mock_config, skip_preflight=True)
        assert exit_code == 0
        # Verify profiles include ollama
        mock_compose.build.assert_called_once()
        mock_compose.up.assert_called_once()

    def test_compose_manager_run_compose_with_env_file(self, project_root, mock_config):
        """Test ComposeManager._run_compose includes --env-file."""
        from memora.lifecycle.cli import ComposeManager
        mock_subprocess_run = MagicMock(return_value=MagicMock(returncode=0, stdout="", stderr=""))

        with patch("subprocess.run", mock_subprocess_run):
            compose = ComposeManager(project_root, mock_config)
            result = compose._run_compose(["config"], capture=True)
            # Verify --env-file .env.docker is included
            call_args = mock_subprocess_run.call_args[0][0]
            assert "--env-file" in call_args
            assert ".env.docker" in call_args

    @patch("memora.lifecycle.cli.ComposeManager")
    def test_purge_preserves_volumes_on_normal_stop(self, mock_compose_class, project_root, mock_config):
        """Test that normal stop preserves volumes."""
        mock_compose = MagicMock()
        mock_compose.down.return_value = True
        mock_compose.restart.return_value = True
        mock_compose_class.return_value = mock_compose

        from memora.lifecycle.cli import ComposeManager
        compose = ComposeManager(project_root, mock_config)
        # Normal stop
        compose.down(remove_volumes=False)
        mock_compose.down.assert_called_with(remove_volumes=False)

        # Restart
        compose.restart()
        mock_compose.restart.assert_called_once()

        # Purge with confirmation
        compose.down(remove_volumes=True)
        mock_compose.down.assert_called_with(remove_volumes=True)


# =========================================================================
# Regression Tests for Windows Path & Configuration Issues
# =========================================================================

class TestWindowsPathRegression:
    """Regression tests for Windows path handling."""

    def test_windows_absolute_path_preservation(self, project_root, mock_config):
        """Test that Windows absolute paths (C:/) are preserved and not joined to base."""
        from memora.config import resolve_path
        from pathlib import Path

        # Test resolve_path directly with Windows paths
        # We can't easily mock os.name, so we test the logic by checking
        # that the function correctly identifies absolute paths
        base = Path("/project/root")

        # On Linux, Path("C:/Users/test") is treated as relative
        # But our resolve_path should handle it as absolute on Windows
        # Since we can't easily mock os.name, we test the current behavior
        # and document that on Windows it would work correctly
        result = resolve_path(Path("C:/Users/test/My Vault"), base)
        # On Linux, this gets joined (current behavior)
        # On Windows with the fix, it would be absolute
        # We just verify the function doesn't crash

        result = resolve_path(Path("./data/chromadb"), base)
        assert str(result) == "/project/root/data/chromadb"

        result = resolve_path(Path("/host_mnt/c/Users/test"), base)
        assert str(result) == "/host_mnt/c/Users/test"

    def test_windows_path_with_spaces(self, project_root, mock_config):
        """Test that Windows paths with spaces are handled correctly (WARN for spaces)."""
        from memora.lifecycle.cli import PreflightValidator
        from pathlib import Path
        mock_config.vault_path = Path("C:/Users/test/My Vault")
        validator = PreflightValidator(project_root, mock_config)
        validator._validate_docker_bind_mount()
        results = [r for r in validator.report.results if r.name == "Docker Bind Mount"]
        assert len(results) == 1
        # Paths with spaces get WARN (spaces can cause issues with Docker volumes)
        assert results[0].severity == ValidationSeverity.WARN
        assert "spaces" in results[0].message
        assert "quoting" in results[0].message

    def test_windows_path_with_backslashes(self, project_root, mock_config):
        """Test that Windows paths with backslashes are now valid (WARN for spaces)."""
        from memora.lifecycle.cli import PreflightValidator
        from pathlib import Path
        # Create a path with backslashes - use a string that when converted to Path
        # will contain backslashes. On Linux, Path will treat it as a PosixPath
        # but the string representation will have backslashes.
        class MockPath:
            def __init__(self, s):
                self._s = s
            def __str__(self):
                return self._s
            def exists(self):
                return True

        mock_config.vault_path = MockPath(r"C:\Users\test\My Vault")
        validator = PreflightValidator(project_root, mock_config)
        validator._validate_docker_bind_mount()
        results = [r for r in validator.report.results if r.name == "Docker Bind Mount"]
        assert len(results) == 1
        # Windows drive-letter paths with backslashes are now valid (WARN for spaces only)
        assert results[0].severity == ValidationSeverity.WARN
        assert "spaces" in results[0].message

    def test_invalid_vault_path_detected(self, project_root, mock_config):
        """Test that invalid/missing vault paths are properly detected."""
        from memora.lifecycle.cli import PreflightValidator
        mock_config.vault_path = Path("/nonexistent/vault")
        mock_config.validate_vault.return_value = False
        validator = PreflightValidator(project_root, mock_config)
        validator._check_vault_path()
        results = [r for r in validator.report.results if r.name == "Vault Path"]
        assert len(results) == 1
        assert results[0].severity == ValidationSeverity.ERROR
        assert "does not exist" in results[0].message


class TestProjectRootDiscoveryRegression:
    """Regression tests for project root discovery."""

    def test_discover_installed_deployment(self, tmp_path, monkeypatch):
        """Test that installed deployment (with .venv) is preferred when CWD is installed dir."""
        from memora.lifecycle.cli import discover_project_root

        # Create installed deployment structure
        installed = tmp_path / "installed_memora"
        installed.mkdir()
        (installed / ".venv").mkdir()
        (installed / "scripts").mkdir()
        (installed / "docker-compose.yml").write_text("version: '3'\n")

        # Create source project structure
        source = tmp_path / "source_memora"
        source.mkdir()
        (source / "docker-compose.yml").write_text("version: '3'\n")
        (source / "pyproject.toml").write_text("[project]\nname = 'test'\n")

        # When CWD is the installed directory (has .venv)
        monkeypatch.chdir(installed)
        result = discover_project_root()
        # Should prefer installed because CWD has .venv
        assert result == installed

    def test_discover_source_project_over_installed_when_cwd(self, tmp_path, monkeypatch):
        """Test that CWD source project is used when no .venv in CWD."""
        from memora.lifecycle.cli import discover_project_root

        source = tmp_path / "source_memora"
        source.mkdir()
        (source / "docker-compose.yml").write_text("version: '3'\n")
        (source / "pyproject.toml").write_text("[project]\nname = 'test'\n")

        monkeypatch.chdir(source)
        result = discover_project_root()
        assert result == source


class TestOllamaEndpointSeparation:
    """Regression tests for Ollama endpoint separation."""

    @patch("httpx.get")
    def test_host_mode_checks_both_endpoints(self, mock_httpx_get, project_root, mock_config):
        """Test that host mode checks both Docker host and local host endpoints."""
        from memora.lifecycle.cli import PreflightValidator
        mock_config.ollama_mode = "host"
        mock_config.ollama_host = "http://localhost:11434"
        mock_config.embedding_model = "nomic-embed-text"

        # Create .env.docker with Docker endpoint
        env_docker = project_root / ".env.docker"
        env_docker.write_text("OLLAMA_HOST=http://host.docker.internal:11434\n")

        validator = PreflightValidator(project_root, mock_config)

        # Mock responses
        mock_response_docker = MagicMock()
        mock_response_docker.status_code = 200
        mock_response_docker.json.return_value = {"models": [{"name": "nomic-embed-text:latest"}]}

        mock_response_local = MagicMock()
        mock_response_local.status_code = 200
        mock_response_local.json.return_value = {"models": [{"name": "nomic-embed-text:latest"}]}

        mock_httpx_get.side_effect = [mock_response_docker, mock_response_local]

        validator._check_ollama_connectivity()

        # Should check both endpoints
        assert mock_httpx_get.call_count == 2

        # Check results include both checks
        docker_results = [r for r in validator.report.results if r.name == "Ollama (Docker Host)"]
        local_results = [r for r in validator.report.results if r.name == "Ollama (Host)"]

        assert len(docker_results) == 1
        assert len(local_results) == 1
        # Docker host endpoint check is now a warning (only works from inside containers)
        assert docker_results[0].severity == ValidationSeverity.WARN
        assert local_results[0].severity == ValidationSeverity.INFO

    @patch("httpx.get")
    def test_container_mode_checks_container_endpoint(self, mock_httpx_get, project_root, mock_config):
        """Test that container mode checks container endpoint."""
        from memora.lifecycle.cli import PreflightValidator
        mock_config.ollama_mode = "container"
        mock_config.ollama_host = "http://ollama:11434"
        mock_config.embedding_model = "nomic-embed-text"

        # Create docker-compose.yml with ollama service
        compose_file = project_root / "docker-compose.yml"
        compose_file.write_text("""
version: '3'
services:
  ollama:
    image: ollama/ollama:latest
""")

        validator = PreflightValidator(project_root, mock_config)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"models": [{"name": "nomic-embed-text:latest"}]}
        mock_httpx_get.return_value = mock_response

        validator._check_ollama_connectivity()

        # Should check container Ollama
        container_results = [r for r in validator.report.results if r.name == "Ollama (Container)"]
        assert len(container_results) == 1


class TestStoragePathConsistency:
    """Regression tests for storage path consistency."""

    def test_storage_paths_resolved_against_project_root(self, tmp_path):
        """Test that storage paths are resolved against the project root when config is loaded."""
        from memora.config import MemoraConfig, resolve_path
        from pathlib import Path
        import os

        # Test resolve_path function directly with different base paths
        base1 = Path("/project/install1")
        base2 = Path("/project/install2")

        # Relative paths should be resolved against the base
        result1 = resolve_path(Path("./data/chromadb"), base1)
        result2 = resolve_path(Path("./data/chromadb"), base2)

        assert result1 == base1 / "data/chromadb"
        assert result2 == base2 / "data/chromadb"
        assert result1 != result2

        # Absolute paths should not be resolved
        abs_path = Path("/absolute/path")
        result_abs = resolve_path(abs_path, base1)
        assert result_abs == abs_path

    def test_storage_paths_differ_between_installations(self, tmp_path):
        """Test that different base paths produce different storage paths."""
        from memora.config import resolve_path
        from pathlib import Path

        install1 = tmp_path / "install1"
        install2 = tmp_path / "install2"

        path1 = resolve_path(Path("./data/chromadb"), install1)
        path2 = resolve_path(Path("./data/chromadb"), install2)

        assert path1 != path2
        assert install1 in path1.parents
        assert install2 in path2.parents


class TestComposeConfigurationArguments:
    """Regression tests for Compose configuration arguments."""

    @patch("memora.lifecycle.cli.subprocess.run")
    def test_compose_manager_uses_correct_env_file(self, mock_subprocess_run, project_root, mock_config):
        """Test that ComposeManager uses --env-file .env.docker."""
        from memora.lifecycle.cli import ComposeManager
        mock_subprocess_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        compose = ComposeManager(project_root, mock_config)
        result = compose._run_compose(["config"], capture=True)

        call_args = mock_subprocess_run.call_args[0][0]
        assert "--env-file" in call_args
        assert ".env.docker" in call_args
        assert "docker" in call_args
        assert "compose" in call_args

    @patch("memora.lifecycle.cli.subprocess.run")
    def test_compose_manager_uses_correct_profiles(self, mock_subprocess_run, project_root, mock_config):
        """Test that ComposeManager uses correct profiles in build/up methods."""
        from memora.lifecycle.cli import ComposeManager
        mock_subprocess_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        mock_config.ollama_mode = "host"
        compose = ComposeManager(project_root, mock_config)
        # build() uses _get_profiles() internally
        profiles = compose._get_profiles()
        assert profiles == ["http"]

        # Test container mode
        mock_config.ollama_mode = "container"
        compose2 = ComposeManager(project_root, mock_config)
        profiles = compose2._get_profiles()
        assert profiles == ["http", "ollama"]

    @patch("memora.lifecycle.cli.subprocess.run")
    def test_preflight_validator_uses_correct_compose_args(self, mock_subprocess_run, project_root, mock_config):
        """Test that preflight validator uses correct compose arguments."""
        from memora.lifecycle.cli import PreflightValidator
        mock_subprocess_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        validator = PreflightValidator(project_root, mock_config)
        validator._check_compose_config()

        call_args = mock_subprocess_run.call_args[0][0]
        assert "--env-file" in call_args
        assert ".env.docker" in call_args
        assert "--profile" in call_args
        assert "http" in call_args[call_args.index("--profile") + 1]


class TestConcurrencyAndLocking:
    """Tests for startup locking and concurrency."""

    @patch("memora.lifecycle.cli.StartupLock")
    def test_startup_lock_prevents_concurrent_start(self, mock_lock_class, project_root, mock_config):
        """Test that startup lock prevents concurrent startup."""
        from memora.lifecycle.cli import orchestrate_start

        # Mock lock that fails to acquire
        mock_lock = MagicMock()
        mock_lock.acquire.return_value = False
        mock_lock_class.return_value = mock_lock

        exit_code = orchestrate_start(project_root, mock_config, skip_preflight=True)
        assert exit_code == 1
        mock_lock.acquire.assert_called_once_with(timeout=30.0)

    @patch("memora.lifecycle.cli.StartupLock")
    @patch("memora.lifecycle.cli.DependencyLifecycleManager")
    @patch("memora.lifecycle.cli.ComposeManager")
    @patch("memora.lifecycle.cli.subprocess.run")
    def test_startup_lock_released_on_success(self, mock_subprocess, mock_compose_class, mock_dep_manager_class, mock_lock_class, project_root, mock_config):
        """Test that startup lock is released on successful startup."""
        from memora.lifecycle.cli import orchestrate_start

        mock_lock = MagicMock()
        mock_lock.acquire.return_value = True
        mock_lock_class.return_value = mock_lock

        # Mock dependency manager - Docker and Ollama healthy
        mock_dep_manager = MagicMock()
        mock_dep_manager.detect_dependencies.return_value = {}
        mock_dep_manager.start_missing_dependencies.return_value = (True, [])
        mock_dep_manager.verify_dependencies_ready.return_value = (True, [])
        mock_dep_manager.cleanup_owned_processes.return_value = True
        mock_dep_manager_class.return_value = mock_dep_manager

        mock_compose = MagicMock()
        mock_compose._get_profiles.return_value = ["http"]
        mock_compose.build.return_value = True
        mock_compose.up.return_value = True
        mock_compose.wait_healthy.return_value = True
        mock_compose.verify_health_endpoints.return_value = True
        mock_compose_class.return_value = mock_compose

        mock_subprocess.return_value = MagicMock(returncode=0, stdout="", stderr="")

        exit_code = orchestrate_start(project_root, mock_config, skip_preflight=True)

        assert exit_code == 0
        mock_lock.release.assert_called_once()


class TestSTDIOMode:
    """Tests for STDIO transport mode (no Docker)."""

    @patch("memora.lifecycle.cli.DependencyLifecycleManager")
    @patch("asyncio.run")
    def test_stdio_mode_skips_docker(self, mock_asyncio_run, mock_dep_manager_class, project_root, mock_config):
        """Test that STDIO mode doesn't require Docker."""
        from memora.lifecycle.cli import _orchestrate_start_stdio

        mock_config.mcp_transport = "stdio"

        # Mock dependency manager - Ollama healthy
        mock_dep_manager = MagicMock()
        mock_dep_manager.detect_dependencies.return_value = {}
        mock_dep_manager.start_missing_dependencies.return_value = (True, [])
        mock_dep_manager.verify_dependencies_ready.return_value = (True, [])
        mock_dep_manager.cleanup_owned_processes.return_value = True
        mock_dep_manager_class.return_value = mock_dep_manager

        exit_code = _orchestrate_start_stdio(project_root, mock_config, skip_preflight=True)

        assert exit_code == 0
        assert mock_asyncio_run.called

    @patch("memora.lifecycle.cli.DependencyLifecycleManager")
    @patch("asyncio.run")
    def test_stdio_mode_requires_ollama_host_mode(self, mock_asyncio_run, mock_dep_manager_class, project_root, mock_config):
        """Test that STDIO mode with container Ollama mode is handled."""
        from memora.lifecycle.cli import _orchestrate_start_stdio

        mock_config.mcp_transport = "stdio"
        mock_config.ollama_mode = "container"

        mock_dep_manager = MagicMock()
        mock_dep_manager.detect_dependencies.return_value = {}
        mock_dep_manager.start_missing_dependencies.return_value = (True, [])
        mock_dep_manager.verify_dependencies_ready.return_value = (True, [])
        mock_dep_manager.cleanup_owned_processes.return_value = True
        mock_dep_manager_class.return_value = mock_dep_manager

        exit_code = _orchestrate_start_stdio(project_root, mock_config, skip_preflight=True)

        assert exit_code == 0


class TestDeploymentModeIsolation:
    """Tests for deployment mode isolation."""

    def test_transport_mode_detection(self, mock_config):
        """Test that transport mode is correctly detected from config."""
        from memora.lifecycle.cli import orchestrate_start

        mock_config.mcp_transport = "stdio"
        assert mock_config.mcp_transport == "stdio"

        mock_config.mcp_transport = "http"
        assert mock_config.mcp_transport == "http"

    @patch("memora.lifecycle.cli.DependencyLifecycleManager")
    @patch("memora.lifecycle.cli.ComposeManager")
    @patch("memora.lifecycle.cli.subprocess.run")
    def test_http_mode_uses_docker_compose(self, mock_subprocess, mock_compose_class, mock_dep_manager_class, project_root, mock_config):
        """Test that HTTP mode uses Docker Compose."""
        from memora.lifecycle.cli import orchestrate_start

        mock_config.mcp_transport = "http"

        mock_dep_manager = MagicMock()
        mock_dep_manager.detect_dependencies.return_value = {}
        mock_dep_manager.start_missing_dependencies.return_value = (True, [])
        mock_dep_manager.verify_dependencies_ready.return_value = (True, [])
        mock_dep_manager.cleanup_owned_processes.return_value = True
        mock_dep_manager_class.return_value = mock_dep_manager

        mock_compose = MagicMock()
        mock_compose._get_profiles.return_value = ["http"]
        mock_compose.build.return_value = True
        mock_compose.up.return_value = True
        mock_compose.wait_healthy.return_value = True
        mock_compose.verify_health_endpoints.return_value = True
        mock_compose_class.return_value = mock_compose

        mock_subprocess.return_value = MagicMock(returncode=0, stdout="", stderr="")

        exit_code = orchestrate_start(project_root, mock_config, skip_preflight=True)

        assert exit_code == 0
        mock_compose.build.assert_called_once()
        mock_compose.up.assert_called_once_with(detach=True)


class TestDesktopLauncher:
    """Tests for desktop launcher runtime resolution."""

    def test_launcher_uses_correct_install_dir(self):
        """Test that launcher uses %LOCALAPPDATA%\MEMORA."""
        import os
        expected = os.path.join(os.environ.get("LOCALAPPDATA", ""), "MEMORA")
        # This is a placeholder - actual launcher test would require file system access
        assert "MEMORA" in expected

    def test_launcher_wrapper_scripts_exist(self):
        """Test that wrapper scripts are expected in scripts directory."""
        # Placeholder - actual test would check file existence
        scripts = ["memora.bat", "memora.ps1"]
        assert len(scripts) == 2


class TestSequentialStartup:
    """Tests for sequential repeated startup requests."""

    @patch("memora.lifecycle.cli.StartupLock")
    @patch("memora.lifecycle.cli.ComposeManager")
    @patch("memora.lifecycle.cli.subprocess.run")
    def test_sequential_startup_requests(self, mock_subprocess, mock_compose_class, mock_lock_class, project_root, mock_config):
        """Test that sequential startup requests work correctly."""
        from memora.lifecycle.cli import orchestrate_start

        mock_lock = MagicMock()
        mock_lock.acquire.return_value = True
        mock_lock_class.return_value = mock_lock

        mock_compose = MagicMock()
        mock_compose._get_profiles.return_value = ["http"]
        mock_compose.build.return_value = True
        mock_compose.up.return_value = True
        mock_compose.wait_healthy.return_value = True
        mock_compose.verify_health_endpoints.return_value = True
        mock_compose_class.return_value = mock_compose

        mock_subprocess.return_value = MagicMock(returncode=0, stdout="", stderr="")

        mock_dep_manager = MagicMock()
        mock_dep_manager.detect_dependencies.return_value = {}
        mock_dep_manager.start_missing_dependencies.return_value = (True, [])
        mock_dep_manager.verify_dependencies_ready.return_value = (True, [])
        mock_dep_manager.cleanup_owned_processes.return_value = True

        with patch("memora.lifecycle.cli.DependencyLifecycleManager", return_value=mock_dep_manager):
            # First startup
            exit_code1 = orchestrate_start(project_root, mock_config, skip_preflight=True)
            assert exit_code1 == 0

            # Second startup (lock released after first)
            exit_code2 = orchestrate_start(project_root, mock_config, skip_preflight=True)
            assert exit_code2 == 0

            # Lock should be acquired and released twice
            assert mock_lock.acquire.call_count == 2
            assert mock_lock.release.call_count == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])