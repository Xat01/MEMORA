"""
Tests for MEMORA Dependency Lifecycle Manager.
"""

import pytest
from unittest.mock import patch, MagicMock, PropertyMock
from pathlib import Path
import sys

from memora.lifecycle.dependency_manager import (
    DependencyLifecycleManager,
    StartupConfig,
    DependencyType,
    DependencyState,
    DependencyInfo,
    DockerDesktopDetector,
    OllamaDetector,
)
from memora.config import MemoraConfig


# Module-level fixtures
@pytest.fixture
def startup_config():
    """Create a StartupConfig with test defaults."""
    return StartupConfig(
        docker_startup_timeout=5,
        docker_startup_interval=1,
        ollama_startup_timeout=5,
        ollama_startup_interval=1,
        verbose=True,
    )


@pytest.fixture
def mock_memora_config():
    """Create a mock MemoraConfig."""
    config = MagicMock(spec=MemoraConfig)
    config.ollama_mode = "host"
    config.ollama_host = "http://localhost:11434"
    config.embedding_model = "nomic-embed-text"
    config.log_level = "INFO"
    return config


class TestStartupConfig:
    """Test StartupConfig defaults and environment overrides."""

    def test_default_values(self):
        """Test default configuration values."""
        config = StartupConfig()
        assert config.docker_startup_timeout == 120
        assert config.docker_startup_interval == 5
        assert config.ollama_startup_timeout == 60
        assert config.ollama_startup_interval == 3
        assert config.ollama_executable == "ollama"
        assert config.verbose is False
        assert config.docker_desktop_path is None

    def test_custom_values(self):
        """Test custom configuration values."""
        config = StartupConfig(
            docker_startup_timeout=30,
            docker_startup_interval=2,
            ollama_startup_timeout=30,
            ollama_startup_interval=2,
            verbose=True,
        )
        assert config.docker_startup_timeout == 30
        assert config.docker_startup_interval == 2
        assert config.ollama_startup_timeout == 30
        assert config.ollama_startup_interval == 2
        assert config.verbose is True


class TestDependencyType:
    """Test DependencyType enum."""

    def test_values(self):
        assert DependencyType.DOCKER_DESKTOP.value == "docker_desktop"
        assert DependencyType.OLLAMA.value == "ollama"


class TestDependencyState:
    """Test DependencyState enum."""

    def test_values(self):
        assert DependencyState.UNKNOWN.value == "unknown"
        assert DependencyState.NOT_INSTALLED.value == "not_installed"
        assert DependencyState.STOPPED.value == "stopped"
        assert DependencyState.STARTING.value == "starting"
        assert DependencyState.RUNNING.value == "running"
        assert DependencyState.FAILED.value == "failed"


class TestDependencyInfo:
    """Test DependencyInfo dataclass."""

    def test_creation(self):
        info = DependencyInfo(type=DependencyType.DOCKER_DESKTOP)
        assert info.type == DependencyType.DOCKER_DESKTOP
        assert info.state == DependencyState.UNKNOWN
        assert info.installed is False
        assert info.executable_path is None
        assert info.process_id is None
        assert info.started_by_memora is False
        assert info.version is None
        assert info.error_message is None
        assert info.details == {}

    def test_with_values(self):
        info = DependencyInfo(
            type=DependencyType.OLLAMA,
            state=DependencyState.RUNNING,
            installed=True,
            executable_path="/usr/bin/ollama",
            process_id=1234,
            started_by_memora=True,
            version="0.1.0",
            details={"api_running": True},
        )
        assert info.type == DependencyType.OLLAMA
        assert info.state == DependencyState.RUNNING
        assert info.installed is True
        assert info.executable_path == "/usr/bin/ollama"
        assert info.process_id == 1234
        assert info.started_by_memora is True
        assert info.version == "0.1.0"
        assert info.details == {"api_running": True}


class TestDockerDesktopDetector:
    """Test DockerDesktopDetector."""

    @pytest.fixture
    def detector(self, startup_config):
        return DockerDesktopDetector(startup_config)

    @patch("shutil.which")
    def test_is_docker_cli_available_true(self, mock_which, detector):
        mock_which.return_value = "/usr/bin/docker"
        assert detector.is_docker_cli_available() is True
        mock_which.assert_called_once_with("docker")

    @patch("shutil.which")
    def test_is_docker_cli_available_false(self, mock_which, detector):
        mock_which.return_value = None
        assert detector.is_docker_cli_available() is False

    @patch("subprocess.run")
    def test_get_docker_version(self, mock_run, detector):
        mock_run.return_value = MagicMock(returncode=0, stdout="Docker version 24.0.0", stderr="")
        version = detector.get_docker_version()
        assert version == "Docker version 24.0.0"

    @patch("subprocess.run")
    def test_get_docker_version_failure(self, mock_run, detector):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="error")
        version = detector.get_docker_version()
        assert version is None

    @patch("subprocess.run")
    def test_is_daemon_running_true(self, mock_run, detector):
        mock_run.return_value = MagicMock(returncode=0, stdout="OK", stderr="")
        assert detector.is_daemon_running() is True

    @patch("subprocess.run")
    def test_is_daemon_running_false(self, mock_run, detector):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="error")
        assert detector.is_daemon_running() is False

    @patch("subprocess.run")
    def test_is_daemon_running_exception(self, mock_run, detector):
        mock_run.side_effect = Exception("error")
        assert detector.is_daemon_running() is False


class TestOllamaDetector:
    """Test OllamaDetector."""

    @pytest.fixture
    def detector(self, startup_config, mock_memora_config):
        return OllamaDetector(startup_config, mock_memora_config)

    @patch("shutil.which")
    def test_is_ollama_installed_true(self, mock_which, detector):
        mock_which.return_value = "/usr/bin/ollama"
        assert detector.is_ollama_installed() is True

    @patch("shutil.which")
    def test_is_ollama_installed_false(self, mock_which, detector):
        mock_which.return_value = None
        assert detector.is_ollama_installed() is False

    @patch("subprocess.run")
    def test_get_ollama_version(self, mock_run, detector):
        mock_run.return_value = MagicMock(returncode=0, stdout="ollama version 0.1.0", stderr="")
        version = detector.get_ollama_version()
        assert version == "ollama version 0.1.0"

    @patch("httpx.get")
    def test_is_ollama_running_true(self, mock_get, detector):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_get.return_value = mock_response
        assert detector.is_ollama_running() is True
        mock_get.assert_called_once_with("http://localhost:11434/api/tags", timeout=5.0)

    @patch("httpx.get")
    def test_is_ollama_running_false(self, mock_get, detector):
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_get.return_value = mock_response
        assert detector.is_ollama_running() is False

    @patch("httpx.get")
    def test_is_ollama_running_exception(self, mock_get, detector):
        import httpx
        mock_get.side_effect = httpx.ConnectError("Connection refused")
        assert detector.is_ollama_running() is False

    @patch("httpx.get")
    def test_is_model_available_true(self, mock_get, detector):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"models": [{"name": "nomic-embed-text:latest"}]}
        mock_get.return_value = mock_response
        assert detector.is_model_available() is True

    @patch("httpx.get")
    def test_is_model_available_false(self, mock_get, detector):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"models": [{"name": "other-model:latest"}]}
        mock_get.return_value = mock_response
        assert detector.is_model_available() is False

    @patch("httpx.get")
    def test_get_available_models(self, mock_get, detector):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"models": [{"name": "model1"}, {"name": "model2"}]}
        mock_get.return_value = mock_response
        models = detector.get_available_models()
        assert models == ["model1", "model2"]


class TestDependencyLifecycleManager:
    """Test DependencyLifecycleManager."""

    @pytest.fixture
    def manager(self, mock_memora_config, startup_config):
        return DependencyLifecycleManager(mock_memora_config, startup_config)

    @patch("memora.lifecycle.dependency_manager.DockerDesktopDetector")
    @patch("memora.lifecycle.dependency_manager.OllamaDetector")
    def test_detect_dependencies(self, mock_ollama_detector_class, mock_docker_detector_class, manager):
        """Test dependency detection."""
        # Setup mocks
        mock_docker = MagicMock()
        mock_docker.is_docker_cli_available.return_value = True
        mock_docker.get_docker_version.return_value = "Docker version 24.0.0"
        mock_docker.find_docker_desktop.return_value = "/path/to/Docker Desktop.exe"
        mock_docker.is_daemon_running.return_value = True
        mock_docker.is_docker_desktop_running.return_value = True
        mock_docker_detector_class.return_value = mock_docker

        mock_ollama = MagicMock()
        mock_ollama.is_ollama_installed.return_value = True
        mock_ollama.get_ollama_version.return_value = "ollama version 0.1.0"
        mock_ollama.is_ollama_running.return_value = True
        mock_ollama.is_model_available.return_value = True
        mock_ollama.get_available_models.return_value = ["nomic-embed-text:latest"]
        mock_ollama_detector_class.return_value = mock_ollama

        # Re-create manager with mocked detectors
        manager.docker_detector = mock_docker
        manager.ollama_detector = mock_ollama

        # Run detection
        result = manager.detect_dependencies()

        # Verify results
        assert DependencyType.DOCKER_DESKTOP in result
        assert DependencyType.OLLAMA in result

        docker_info = result[DependencyType.DOCKER_DESKTOP]
        assert docker_info.installed is True
        assert docker_info.version == "Docker version 24.0.0"
        assert docker_info.state == DependencyState.RUNNING
        assert docker_info.details["daemon_running"] is True

        ollama_info = result[DependencyType.OLLAMA]
        assert ollama_info.installed is True
        assert ollama_info.version == "ollama version 0.1.0"
        assert ollama_info.state == DependencyState.RUNNING
        assert ollama_info.details["model_available"] is True

    @patch("memora.lifecycle.dependency_manager.DockerDesktopDetector")
    @patch("memora.lifecycle.dependency_manager.OllamaDetector")
    def test_detect_dependencies_docker_not_installed(self, mock_ollama_detector_class, mock_docker_detector_class, manager):
        """Test dependency detection when Docker is not installed."""
        mock_docker = MagicMock()
        mock_docker.is_docker_cli_available.return_value = False
        mock_docker.find_docker_desktop.return_value = None
        mock_docker.is_daemon_running.return_value = False
        mock_docker.is_docker_desktop_running.return_value = False
        mock_docker_detector_class.return_value = mock_docker

        mock_ollama = MagicMock()
        mock_ollama.is_ollama_installed.return_value = True
        mock_ollama.is_ollama_running.return_value = True
        mock_ollama.is_model_available.return_value = True
        mock_ollama.get_available_models.return_value = ["nomic-embed-text:latest"]
        mock_ollama_detector_class.return_value = mock_ollama

        manager.docker_detector = mock_docker
        manager.ollama_detector = mock_ollama

        result = manager.detect_dependencies()

        docker_info = result[DependencyType.DOCKER_DESKTOP]
        assert docker_info.installed is False
        assert docker_info.state == DependencyState.NOT_INSTALLED
        assert docker_info.error_message == "Docker CLI not found in PATH"

    @patch("memora.lifecycle.dependency_manager.DockerDesktopDetector")
    @patch("memora.lifecycle.dependency_manager.OllamaDetector")
    def test_start_missing_dependencies_docker_already_running(self, mock_ollama_detector_class, mock_docker_detector_class, manager):
        """Test starting dependencies when Docker is already running."""
        mock_docker = MagicMock()
        mock_docker.is_daemon_running.return_value = True
        mock_docker_detector_class.return_value = mock_docker

        mock_ollama = MagicMock()
        mock_ollama.is_ollama_running.return_value = True
        mock_ollama.is_model_available.return_value = True
        mock_ollama_detector_class.return_value = mock_ollama

        manager.docker_detector = mock_docker
        manager.ollama_detector = mock_ollama

        # Pre-populate dependency info
        manager._dependency_info = {
            DependencyType.DOCKER_DESKTOP: DependencyInfo(
                type=DependencyType.DOCKER_DESKTOP,
                installed=True,
                state=DependencyState.RUNNING,
            ),
            DependencyType.OLLAMA: DependencyInfo(
                type=DependencyType.OLLAMA,
                installed=True,
                state=DependencyState.RUNNING,
            ),
        }

        success, errors = manager.start_missing_dependencies()

        assert success is True
        assert errors == []
        # Docker should not be started since it's already running
        mock_docker.start_docker_desktop.assert_not_called()

    @patch("memora.lifecycle.dependency_manager.DockerDesktopDetector")
    @patch("memora.lifecycle.dependency_manager.OllamaDetector")
    def test_start_missing_dependencies_docker_needs_start(self, mock_ollama_detector_class, mock_docker_detector_class, manager):
        """Test starting Docker when it's installed but not running."""
        mock_docker = MagicMock()
        mock_docker.start_docker_desktop.return_value = (True, 1234, None)
        mock_docker_detector_class.return_value = mock_docker

        mock_ollama = MagicMock()
        mock_ollama.is_ollama_running.return_value = True
        mock_ollama.is_model_available.return_value = True
        mock_ollama_detector_class.return_value = mock_ollama

        manager.docker_detector = mock_docker
        manager.ollama_detector = mock_ollama

        manager._dependency_info = {
            DependencyType.DOCKER_DESKTOP: DependencyInfo(
                type=DependencyType.DOCKER_DESKTOP,
                installed=True,
                state=DependencyState.STOPPED,
            ),
            DependencyType.OLLAMA: DependencyInfo(
                type=DependencyType.OLLAMA,
                installed=True,
                state=DependencyState.RUNNING,
            ),
        }

        success, errors = manager.start_missing_dependencies()

        assert success is True
        assert errors == []
        mock_docker.start_docker_desktop.assert_called_once()
        assert manager._started_processes[DependencyType.DOCKER_DESKTOP] == 1234
        assert manager._dependency_info[DependencyType.DOCKER_DESKTOP].started_by_memora is True

    @patch("memora.lifecycle.dependency_manager.DockerDesktopDetector")
    @patch("memora.lifecycle.dependency_manager.OllamaDetector")
    def test_start_missing_dependencies_docker_fails(self, mock_ollama_detector_class, mock_docker_detector_class, manager):
        """Test handling Docker start failure."""
        mock_docker = MagicMock()
        mock_docker.start_docker_desktop.return_value = (False, None, "Failed to start")
        mock_docker_detector_class.return_value = mock_docker

        mock_ollama = MagicMock()
        mock_ollama.is_ollama_running.return_value = True
        mock_ollama.is_model_available.return_value = True
        mock_ollama_detector_class.return_value = mock_ollama

        manager.docker_detector = mock_docker
        manager.ollama_detector = mock_ollama

        manager._dependency_info = {
            DependencyType.DOCKER_DESKTOP: DependencyInfo(
                type=DependencyType.DOCKER_DESKTOP,
                installed=True,
                state=DependencyState.STOPPED,
            ),
            DependencyType.OLLAMA: DependencyInfo(
                type=DependencyType.OLLAMA,
                installed=True,
                state=DependencyState.RUNNING,
            ),
        }

        success, errors = manager.start_missing_dependencies()

        assert success is False
        assert "Docker Desktop: Failed to start" in errors
        assert manager._dependency_info[DependencyType.DOCKER_DESKTOP].state == DependencyState.FAILED

    @patch("memora.lifecycle.dependency_manager.DockerDesktopDetector")
    @patch("memora.lifecycle.dependency_manager.OllamaDetector")
    def test_start_missing_dependencies_ollama_host_mode(self, mock_ollama_detector_class, mock_docker_detector_class, manager):
        """Test starting Ollama in host mode."""
        mock_docker = MagicMock()
        mock_docker.is_daemon_running.return_value = True
        mock_docker_detector_class.return_value = mock_docker

        mock_ollama = MagicMock()
        mock_ollama.start_ollama_serve.return_value = (True, 5678, None)
        mock_ollama_detector_class.return_value = mock_ollama

        manager.docker_detector = mock_docker
        manager.ollama_detector = mock_ollama

        manager._dependency_info = {
            DependencyType.DOCKER_DESKTOP: DependencyInfo(
                type=DependencyType.DOCKER_DESKTOP,
                installed=True,
                state=DependencyState.RUNNING,
            ),
            DependencyType.OLLAMA: DependencyInfo(
                type=DependencyType.OLLAMA,
                installed=True,
                state=DependencyState.STOPPED,
            ),
        }

        success, errors = manager.start_missing_dependencies()

        assert success is True
        mock_ollama.start_ollama_serve.assert_called_once()
        assert manager._started_processes[DependencyType.OLLAMA] == 5678
        assert manager._dependency_info[DependencyType.OLLAMA].started_by_memora is True

    @patch("memora.lifecycle.dependency_manager.DockerDesktopDetector")
    @patch("memora.lifecycle.dependency_manager.OllamaDetector")
    def test_start_missing_dependencies_ollama_container_mode(self, mock_ollama_detector_class, mock_docker_detector_class, manager):
        """Test that Ollama is not started in container mode."""
        manager.memora_config.ollama_mode = "container"

        mock_docker = MagicMock()
        mock_docker.is_daemon_running.return_value = True
        mock_docker_detector_class.return_value = mock_docker

        mock_ollama = MagicMock()
        mock_ollama_detector_class.return_value = mock_ollama

        manager.docker_detector = mock_docker
        manager.ollama_detector = mock_ollama

        manager._dependency_info = {
            DependencyType.DOCKER_DESKTOP: DependencyInfo(
                type=DependencyType.DOCKER_DESKTOP,
                installed=True,
                state=DependencyState.RUNNING,
            ),
            DependencyType.OLLAMA: DependencyInfo(
                type=DependencyType.OLLAMA,
                installed=True,
                state=DependencyState.STOPPED,
            ),
        }

        success, errors = manager.start_missing_dependencies()

        assert success is True
        mock_ollama.start_ollama_serve.assert_not_called()
        assert manager._dependency_info[DependencyType.OLLAMA].details.get("managed_by") == "docker_compose"

    @patch("memora.lifecycle.dependency_manager.DockerDesktopDetector")
    @patch("memora.lifecycle.dependency_manager.OllamaDetector")
    def test_verify_dependencies_ready_success(self, mock_ollama_detector_class, mock_docker_detector_class, manager):
        """Test verifying dependencies when all are ready."""
        mock_docker = MagicMock()
        mock_docker.is_daemon_running.return_value = True
        mock_docker_detector_class.return_value = mock_docker

        mock_ollama = MagicMock()
        mock_ollama.is_ollama_running.return_value = True
        mock_ollama.is_model_available.return_value = True
        mock_ollama_detector_class.return_value = mock_ollama

        manager.docker_detector = mock_docker
        manager.ollama_detector = mock_ollama

        success, issues = manager.verify_dependencies_ready()

        assert success is True
        assert issues == []

    @patch("memora.lifecycle.dependency_manager.DockerDesktopDetector")
    @patch("memora.lifecycle.dependency_manager.OllamaDetector")
    def test_verify_dependencies_ready_docker_failed(self, mock_ollama_detector_class, mock_docker_detector_class, manager):
        """Test verifying dependencies when Docker daemon not ready."""
        mock_docker = MagicMock()
        mock_docker.is_daemon_running.return_value = False
        mock_docker_detector_class.return_value = mock_docker

        mock_ollama = MagicMock()
        mock_ollama.is_ollama_running.return_value = True
        mock_ollama.is_model_available.return_value = True
        mock_ollama_detector_class.return_value = mock_ollama

        manager.docker_detector = mock_docker
        manager.ollama_detector = mock_ollama

        success, issues = manager.verify_dependencies_ready()

        assert success is False
        assert "Docker daemon not responsive" in issues

    @patch("memora.lifecycle.dependency_manager.DockerDesktopDetector")
    @patch("memora.lifecycle.dependency_manager.OllamaDetector")
    def test_verify_dependencies_ready_ollama_model_missing(self, mock_ollama_detector_class, mock_docker_detector_class, manager):
        """Test verifying dependencies when Ollama model is missing (warning only)."""
        mock_docker = MagicMock()
        mock_docker.is_daemon_running.return_value = True
        mock_docker_detector_class.return_value = mock_docker

        mock_ollama = MagicMock()
        mock_ollama.is_ollama_running.return_value = True
        mock_ollama.is_model_available.return_value = False
        mock_ollama_detector_class.return_value = mock_ollama

        manager.docker_detector = mock_docker
        manager.ollama_detector = mock_ollama

        success, issues = manager.verify_dependencies_ready()

        assert success is True  # Model missing is warning, not failure
        # Model missing should not be in issues (it's logged as warning)

    @patch("memora.lifecycle.dependency_manager.DockerDesktopDetector")
    @patch("memora.lifecycle.dependency_manager.OllamaDetector")
    def test_get_startup_report(self, mock_ollama_detector_class, mock_docker_detector_class, manager):
        """Test generating startup report."""
        mock_docker = MagicMock()
        mock_ollama = MagicMock()
        mock_docker_detector_class.return_value = mock_docker
        mock_ollama_detector_class.return_value = mock_ollama

        manager.docker_detector = mock_docker
        manager.ollama_detector = mock_ollama

        manager._dependency_info = {
            DependencyType.DOCKER_DESKTOP: DependencyInfo(
                type=DependencyType.DOCKER_DESKTOP,
                installed=True,
                state=DependencyState.RUNNING,
                started_by_memora=True,
                version="24.0.0",
            ),
            DependencyType.OLLAMA: DependencyInfo(
                type=DependencyType.OLLAMA,
                installed=True,
                state=DependencyState.RUNNING,
                started_by_memora=False,
                version="0.1.0",
                details={"model_available": True},
            ),
        }
        manager._started_processes = {DependencyType.DOCKER_DESKTOP: 1234}

        report = manager.get_startup_report()

        assert report["docker"]["installed"] is True
        assert report["docker"]["state"] == "running"
        assert report["docker"]["started_by_memora"] is True
        assert report["docker"]["version"] == "24.0.0"

        assert report["ollama"]["installed"] is True
        assert report["ollama"]["state"] == "running"
        assert report["ollama"]["started_by_memora"] is False
        assert report["ollama"]["version"] == "0.1.0"
        assert report["ollama"]["model_available"] is True
        assert report["ollama"]["mode"] == "host"

        assert report["started_processes"]["docker_desktop"] == 1234

    @patch("memora.lifecycle.dependency_manager.OllamaDetector")
    def test_cleanup_owned_processes_ollama(self, mock_ollama_detector_class, manager):
        """Test cleaning up MEMORA-owned Ollama process."""
        mock_ollama = MagicMock()
        mock_ollama.stop_ollama_if_owned.return_value = True
        mock_ollama_detector_class.return_value = mock_ollama

        manager.ollama_detector = mock_ollama
        manager._dependency_info = {
            DependencyType.OLLAMA: DependencyInfo(
                type=DependencyType.OLLAMA,
                installed=True,
                state=DependencyState.RUNNING,
                started_by_memora=True,
            ),
        }

        success = manager.cleanup_owned_processes()

        assert success is True
        mock_ollama.stop_ollama_if_owned.assert_called_once()

    def test_cleanup_owned_processes_no_ollama(self, manager):
        """Test cleanup when no Ollama process owned."""
        manager._dependency_info = {
            DependencyType.OLLAMA: DependencyInfo(
                type=DependencyType.OLLAMA,
                installed=True,
                state=DependencyState.RUNNING,
                started_by_memora=False,
            ),
        }

        success = manager.cleanup_owned_processes()

        assert success is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])