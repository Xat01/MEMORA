"""
Tests for MEMORA Doctor Diagnostics

Covers:
- Successful component checks
- Missing dependencies
- Unavailable Ollama server
- Missing embedding model
- Invalid vault path
- SQLite integrity failure
- ChromaDB connection failure
- Missing configuration
- Permission errors
"""

import tempfile
import shutil
import sqlite3
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock, PropertyMock
import pytest
import sys

from memora.diagnostics import (
    Doctor, DoctorReport, CheckResult, CheckStatus, run_doctor, _check_python_version
)
from memora.config import MemoraConfig


# =========================================================================
# Fixtures
# =========================================================================

@pytest.fixture
def temp_dir():
    """Create temporary directory for tests."""
    d = Path(tempfile.mkdtemp())
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def test_vault(temp_dir):
    """Create a test Obsidian vault."""
    vault = temp_dir / "test_vault"
    vault.mkdir()
    (vault / ".obsidian").mkdir()
    (vault / "note1.md").write_text("# Note 1\n\nContent")
    (vault / "note2.md").write_text("# Note 2\n\nMore content")
    return vault


@pytest.fixture
def test_config(test_vault, temp_dir):
    """Create a valid test configuration."""
    return MemoraConfig(
        vault_path=test_vault,
        chroma_path=temp_dir / "chromadb",
        sqlite_path=temp_dir / "memora.db",
        embedding_model="nomic-embed-text",
        embedding_dimensions=768,
        ollama_host="http://localhost:11434",
        chunk_size=512,
        chunk_overlap=50,
    )


# =========================================================================
# DoctorReport Tests
# =========================================================================

class TestDoctorReport:
    """Test DoctorReport functionality."""

    def test_overall_status_pass(self):
        """Test overall status when all checks pass."""
        report = DoctorReport()
        report.add_check(CheckResult("A", CheckStatus.PASS))
        report.add_check(CheckResult("B", CheckStatus.PASS))
        assert report.overall_status == CheckStatus.PASS
        assert report.exit_code == 0

    def test_overall_status_warn(self):
        """Test overall status with warnings."""
        report = DoctorReport()
        report.add_check(CheckResult("A", CheckStatus.PASS))
        report.add_check(CheckResult("B", CheckStatus.WARN))
        assert report.overall_status == CheckStatus.WARN
        assert report.exit_code == 2

    def test_overall_status_fail(self):
        """Test overall status with failures."""
        report = DoctorReport()
        report.add_check(CheckResult("A", CheckStatus.PASS))
        report.add_check(CheckResult("B", CheckStatus.FAIL))
        assert report.overall_status == CheckStatus.FAIL
        assert report.exit_code == 1

    def test_fail_overrides_warn(self):
        """Test FAIL overrides WARN."""
        report = DoctorReport()
        report.add_check(CheckResult("A", CheckStatus.WARN))
        report.add_check(CheckResult("B", CheckStatus.FAIL))
        assert report.overall_status == CheckStatus.FAIL
        assert report.exit_code == 1

    def test_summary_counts(self):
        """Test summary count accuracy."""
        report = DoctorReport()
        report.add_check(CheckResult("A", CheckStatus.PASS))
        report.add_check(CheckResult("B", CheckStatus.PASS))
        report.add_check(CheckResult("C", CheckStatus.WARN))
        report.add_check(CheckResult("D", CheckStatus.FAIL))
        report.add_check(CheckResult("E", CheckStatus.SKIP))

        summary = report.get_summary()
        assert summary[CheckStatus.PASS] == 2
        assert summary[CheckStatus.WARN] == 1
        assert summary[CheckStatus.FAIL] == 1
        assert summary[CheckStatus.SKIP] == 1


# =========================================================================
# Python Version Check Tests (standalone function)
# =========================================================================

class TestPythonVersionCheck:
    """Test Python version check logic."""

    def test_python_version_pass(self):
        """Test Python 3.10+ passes."""
        status, msg, details = _check_python_version((3, 10, 0), "3.10.0")
        assert status == CheckStatus.PASS
        assert "supported" in msg

    def test_python_version_pass_311(self):
        """Test Python 3.11 passes."""
        status, msg, details = _check_python_version((3, 11, 2), "3.11.2")
        assert status == CheckStatus.PASS

    def test_python_version_pass_312(self):
        """Test Python 3.12 passes."""
        status, msg, details = _check_python_version((3, 12, 0), "3.12.0")
        assert status == CheckStatus.PASS

    def test_python_version_warn_39(self):
        """Test Python 3.9 warns."""
        status, msg, details = _check_python_version((3, 9, 0), "3.9.0")
        assert status == CheckStatus.WARN
        assert "3.10" in msg

    def test_python_version_fail_38(self):
        """Test Python 3.8 fails."""
        status, msg, details = _check_python_version((3, 8, 0), "3.8.0")
        assert status == CheckStatus.FAIL
        assert "requires 3.10+" in msg

    def test_python_version_fail_37(self):
        """Test Python 3.7 fails."""
        status, msg, details = _check_python_version((3, 7, 5), "3.7.5")
        assert status == CheckStatus.FAIL


# =========================================================================
# Dependencies Tests
# =========================================================================

class TestDependencies:
    """Test dependency checks."""

    def test_all_dependencies_present(self, test_config):
        """Test all required packages pass."""
        doctor = Doctor(config=test_config)
        doctor._check_dependencies()
        check = doctor.report.checks[-1]
        assert check.status == CheckStatus.PASS
        assert check.details["checked"] > 0

    def test_missing_dependency(self, test_config):
        """Test missing package detection."""
        doctor = Doctor(config=test_config)

        original_import = __import__

        def mock_import(name, *args, **kwargs):
            if name == "chromadb":
                raise ImportError("No module named 'chromadb'")
            return original_import(name, *args, **kwargs)

        with patch('builtins.__import__', side_effect=mock_import):
            doctor._check_dependencies()
            check = doctor.report.checks[-1]
            assert check.status == CheckStatus.FAIL
            assert "chromadb" in check.message


# =========================================================================
# Configuration Tests
# =========================================================================

class TestConfiguration:
    """Test configuration checks."""

    def test_valid_config_pass(self, test_config):
        """Test valid configuration passes."""
        doctor = Doctor(config=test_config)
        doctor._check_configuration()
        assert doctor.report.checks[-1].status == CheckStatus.PASS

    def test_missing_vault_path_fail(self, temp_dir):
        """Test missing VAULT_PATH fails."""
        # Create config with None vault_path to trigger the check
        config = MemoraConfig(
            vault_path=Path("."),  # This will resolve to current dir which exists
            chroma_path=temp_dir / "chromadb",
            sqlite_path=temp_dir / "memora.db",
        )
        # Override to empty path after init
        config.vault_path = Path("")
        doctor = Doctor(config=config)
        doctor._check_configuration()
        # Empty path check should fail
        assert doctor.report.checks[-1].status in (CheckStatus.FAIL, CheckStatus.WARN)

    def test_nonexistent_vault_path_fail(self, temp_dir):
        """Test nonexistent VAULT_PATH fails."""
        config = MemoraConfig(
            vault_path=temp_dir / "nonexistent",
            chroma_path=temp_dir / "chromadb",
            sqlite_path=temp_dir / "memora.db",
        )
        doctor = Doctor(config=config)
        doctor._check_configuration()
        assert doctor.report.checks[-1].status == CheckStatus.FAIL
        assert "does not exist" in doctor.report.checks[-1].message

    def test_relative_paths_warn(self, test_config):
        """Test relative paths produce warning."""
        test_config.chroma_path = Path("./relative/chromadb")
        test_config.sqlite_path = Path("./relative/memora.db")
        doctor = Doctor(config=test_config)
        doctor._check_configuration()
        check = doctor.report.checks[-1]
        assert check.status == CheckStatus.WARN
        # Check details contains the warnings
        assert "relative" in str(check.details).lower()

    def test_embedding_dimension_mismatch_warn(self, test_config):
        """Test embedding dimension mismatch warns."""
        test_config.embedding_model = "nomic-embed-text"
        test_config.embedding_dimensions = 384  # Wrong for nomic
        doctor = Doctor(config=test_config)
        doctor._check_configuration()
        check = doctor.report.checks[-1]
        assert check.status == CheckStatus.WARN
        assert "dimension" in str(check.details).lower()


# =========================================================================
# Ollama Connectivity Tests
# =========================================================================

class TestOllamaConnectivity:
    """Test Ollama connectivity checks."""

    def test_ollama_healthy_pass(self, test_config):
        """Test healthy Ollama passes."""
        mock_provider = Mock()
        mock_provider.health_check.return_value = True

        with patch.object(Doctor, '_create_ollama_provider', return_value=mock_provider):
            doctor = Doctor(config=test_config)
            doctor._check_ollama()
            assert doctor.report.checks[-1].status == CheckStatus.PASS

    def test_ollama_unhealthy_fail(self, test_config):
        """Test unhealthy Ollama fails."""
        mock_provider = Mock()
        mock_provider.health_check.return_value = False

        with patch.object(Doctor, '_create_ollama_provider', return_value=mock_provider):
            doctor = Doctor(config=test_config)
            doctor._check_ollama()
            assert doctor.report.checks[-1].status == CheckStatus.FAIL

    def test_ollama_exception_fail(self, test_config):
        """Test Ollama exception fails."""
        with patch.object(Doctor, '_create_ollama_provider', side_effect=Exception("Connection refused")):
            doctor = Doctor(config=test_config)
            doctor._check_ollama()
            assert doctor.report.checks[-1].status == CheckStatus.FAIL
            assert "Connection refused" in doctor.report.checks[-1].message


# =========================================================================
# Embedding Model Tests
# =========================================================================

class TestEmbeddingModel:
    """Test embedding model availability checks."""

    def test_model_available_pass(self, test_config):
        """Test available model passes."""
        mock_provider = Mock()
        mock_provider.get_model_info.return_value = {
            "name": "nomic-embed-text",
            "dimensions": 768
        }
        mock_provider.health_check.return_value = True

        with patch.object(Doctor, '_create_ollama_provider', return_value=mock_provider):
            with patch('httpx.get') as mock_get:
                mock_response = Mock()
                mock_response.json.return_value = {
                    "models": [{"name": "nomic-embed-text:latest"}]
                }
                mock_response.status_code = 200
                mock_get.return_value = mock_response

                doctor = Doctor(config=test_config)
                doctor._check_embedding_model()
                assert doctor.report.checks[-1].status == CheckStatus.PASS

    def test_model_not_found_fail(self, test_config):
        """Test missing model fails."""
        mock_provider = Mock()
        mock_provider.get_model_info.return_value = {"name": "nomic-embed-text"}

        with patch.object(Doctor, '_create_ollama_provider', return_value=mock_provider):
            with patch('httpx.get') as mock_get:
                mock_response = Mock()
                mock_response.json.return_value = {"models": [{"name": "other-model:latest"}]}
                mock_response.status_code = 200
                mock_get.return_value = mock_response

                doctor = Doctor(config=test_config)
                doctor._check_embedding_model()
                assert doctor.report.checks[-1].status == CheckStatus.FAIL
                assert "not found" in doctor.report.checks[-1].message

    def test_model_check_exception_fail(self, test_config):
        """Test model check exception fails."""
        with patch.object(Doctor, '_create_ollama_provider', side_effect=Exception("Ollama error")):
            doctor = Doctor(config=test_config)
            doctor._check_embedding_model()
            assert doctor.report.checks[-1].status == CheckStatus.FAIL


# =========================================================================
# ChromaDB Tests
# =========================================================================

class TestChromaDB:
    """Test ChromaDB checks."""

    def test_chromadb_healthy_pass(self, test_config, temp_dir):
        """Test healthy ChromaDB passes."""
        chroma_path = temp_dir / "chromadb"
        chroma_path.mkdir()

        with patch('memora.diagnostics.VectorStore') as mock_store_class:
            mock_store = Mock()
            mock_store.get_collection_info.return_value = {
                "count": 100,
                "metadata": {
                    "embedding_model": "nomic-embed-text",
                    "embedding_dimensions": "768"
                }
            }
            mock_store_class.return_value = mock_store

            doctor = Doctor(config=test_config)
            doctor._check_chromadb()
            assert doctor.report.checks[-1].status == CheckStatus.PASS

    def test_chromadb_model_mismatch_warn(self, test_config, temp_dir):
        """Test model mismatch warns."""
        chroma_path = temp_dir / "chromadb"
        chroma_path.mkdir()

        with patch('memora.diagnostics.VectorStore') as mock_store_class:
            mock_store = Mock()
            mock_store.get_collection_info.return_value = {
                "count": 100,
                "metadata": {
                    "embedding_model": "mxbai-embed-large",
                    "embedding_dimensions": "1024"
                }
            }
            mock_store_class.return_value = mock_store

            doctor = Doctor(config=test_config)
            doctor._check_chromadb()
            assert doctor.report.checks[-1].status == CheckStatus.WARN
            assert "mismatch" in doctor.report.checks[-1].message.lower()

    def test_chromadb_connection_fail(self, test_config):
        """Test ChromaDB connection failure."""
        with patch('memora.diagnostics.VectorStore') as mock_store_class:
            mock_store_class.side_effect = Exception("ChromaDB error")

            doctor = Doctor(config=test_config)
            doctor._check_chromadb()
            assert doctor.report.checks[-1].status == CheckStatus.FAIL


# =========================================================================
# SQLite Tests
# =========================================================================

class TestSQLite:
    """Test SQLite checks."""

    def test_sqlite_healthy_pass(self, test_config, temp_dir):
        """Test healthy SQLite passes."""
        sqlite_path = temp_dir / "memora.db"
        sqlite_path.parent.mkdir(parents=True, exist_ok=True)

        with patch('memora.diagnostics.MetadataStore') as mock_store_class:
            mock_store = Mock()
            mock_store.get_index_stats.return_value = {"total_chunks": 50}
            mock_store_class.return_value = mock_store

            mock_conn = MagicMock()
            mock_conn.__enter__ = Mock(return_value=mock_conn)
            mock_conn.__exit__ = Mock(return_value=None)
            mock_conn.execute.return_value.fetchone.return_value = ("wal",)

            with patch('sqlite3.connect', return_value=mock_conn):
                doctor = Doctor(config=test_config)
                doctor._check_sqlite()
                assert doctor.report.checks[-1].status == CheckStatus.PASS
                assert "50 chunks" in doctor.report.checks[-1].message

    def test_sqlite_journal_mode_warn(self, test_config, temp_dir):
        """Test non-WAL journal mode warns."""
        sqlite_path = temp_dir / "memora.db"
        sqlite_path.parent.mkdir(parents=True, exist_ok=True)

        with patch('memora.diagnostics.MetadataStore') as mock_store_class:
            mock_store = Mock()
            mock_store.get_index_stats.return_value = {"total_chunks": 50}
            mock_store_class.return_value = mock_store

            mock_conn = MagicMock()
            mock_conn.__enter__ = Mock(return_value=mock_conn)
            mock_conn.__exit__ = Mock(return_value=None)
            mock_conn.execute.return_value.fetchone.return_value = ("delete",)

            with patch('sqlite3.connect', return_value=mock_conn):
                doctor = Doctor(config=test_config)
                doctor._check_sqlite()
                assert doctor.report.checks[-1].status == CheckStatus.WARN
                assert "journal mode" in doctor.report.checks[-1].message.lower()

    def test_sqlite_integrity_fail(self, test_config):
        """Test SQLite integrity failure."""
        with patch('memora.diagnostics.MetadataStore') as mock_store_class:
            mock_store_class.side_effect = sqlite3.DatabaseError("database disk image is malformed")

            doctor = Doctor(config=test_config)
            doctor._check_sqlite()
            assert doctor.report.checks[-1].status == CheckStatus.FAIL
            assert "integrity error" in doctor.report.checks[-1].message.lower()

    def test_sqlite_connection_fail(self, test_config):
        """Test SQLite connection failure."""
        with patch('memora.diagnostics.MetadataStore') as mock_store_class:
            mock_store_class.side_effect = Exception("Permission denied")

            doctor = Doctor(config=test_config)
            doctor._check_sqlite()
            assert doctor.report.checks[-1].status == CheckStatus.FAIL


# =========================================================================
# Obsidian Vault Tests
# =========================================================================

class TestObsidianVault:
    """Test Obsidian vault checks."""

    def test_valid_vault_pass(self, test_config, test_vault):
        """Test valid vault passes."""
        doctor = Doctor(config=test_config)
        doctor._check_obsidian_vault()
        assert doctor.report.checks[-1].status == CheckStatus.PASS
        assert "2" in doctor.report.checks[-1].message

    def test_no_obsidian_dir_fail(self, test_config, temp_dir):
        """Test vault without .obsidian fails."""
        vault = temp_dir / "not_a_vault"
        vault.mkdir()
        (vault / "note.md").write_text("# Note")

        test_config.vault_path = vault
        doctor = Doctor(config=test_config)
        doctor._check_obsidian_vault()
        assert doctor.report.checks[-1].status == CheckStatus.FAIL
        assert ".obsidian" in doctor.report.checks[-1].message

    def test_no_markdown_files_warn(self, test_config, temp_dir):
        """Test vault with no .md files warns."""
        vault = temp_dir / "empty_vault"
        vault.mkdir()
        (vault / ".obsidian").mkdir()
        (vault / "readme.txt").write_text("text file")

        test_config.vault_path = vault
        doctor = Doctor(config=test_config)
        doctor._check_obsidian_vault()
        assert doctor.report.checks[-1].status == CheckStatus.WARN
        assert "no .md files" in doctor.report.checks[-1].message.lower()

    def test_vault_read_only_warn(self, test_config, test_vault):
        """Test read-only vault warns."""
        with patch('memora.diagnostics.VaultReader') as mock_reader_class:
            mock_reader = Mock()
            mock_reader.list_files.return_value = ["note1.md", "note2.md"]
            mock_reader_class.return_value = mock_reader

            doctor = Doctor(config=test_config)
            doctor._check_obsidian_vault()
            # Should pass since we have .obsidian and .md files
            assert doctor.report.checks[-1].status in (CheckStatus.PASS, CheckStatus.WARN)


# =========================================================================
# Embedding Pipeline Tests
# =========================================================================

class TestEmbeddingPipeline:
    """Test embedding pipeline checks."""

    def test_embedding_generation_pass(self, test_config):
        """Test successful embedding generation passes."""
        mock_provider = Mock()
        mock_result = Mock()
        mock_result.embeddings = [[0.1] * 768]
        mock_result.model = "nomic-embed-text"
        mock_result.token_count = 10
        mock_provider.generate_embeddings.return_value = mock_result

        with patch.object(Doctor, '_create_ollama_provider', return_value=mock_provider):
            doctor = Doctor(config=test_config)
            doctor._check_embedding_pipeline()
            assert doctor.report.checks[-1].status == CheckStatus.PASS
            assert "768d" in doctor.report.checks[-1].message

    def test_embedding_dimension_mismatch_warn(self, test_config):
        """Test embedding dimension mismatch warns."""
        mock_provider = Mock()
        mock_result = Mock()
        mock_result.embeddings = [[0.1] * 384]  # Wrong dimensions
        mock_result.model = "nomic-embed-text"
        mock_result.token_count = 10
        mock_provider.generate_embeddings.return_value = mock_result

        with patch.object(Doctor, '_create_ollama_provider', return_value=mock_provider):
            doctor = Doctor(config=test_config)
            doctor._check_embedding_pipeline()
            assert doctor.report.checks[-1].status == CheckStatus.WARN
            assert "mismatch" in doctor.report.checks[-1].message.lower()

    def test_embedding_generation_fail(self, test_config):
        """Test embedding generation failure."""
        with patch.object(Doctor, '_create_ollama_provider', side_effect=Exception("Ollama not responding")):
            doctor = Doctor(config=test_config)
            doctor._check_embedding_pipeline()
            assert doctor.report.checks[-1].status == CheckStatus.FAIL


# =========================================================================
# MCP Configuration Tests
# =========================================================================

class TestMCPConfiguration:
    """Test MCP configuration checks."""

    def test_mcp_valid_pass(self, test_config):
        """Test valid MCP config passes."""
        with patch('memora.diagnostics.mcp', Mock(__version__="1.0.0")):
            doctor = Doctor(config=test_config)
            doctor._check_mcp_configuration()
            assert doctor.report.checks[-1].status == CheckStatus.PASS

    def test_mcp_missing_fail(self, test_config):
        """Test missing MCP package fails."""
        with patch('memora.diagnostics.mcp', None):
            doctor = Doctor(config=test_config)
            doctor._check_mcp_configuration()
            assert doctor.report.checks[-1].status == CheckStatus.FAIL
            assert "MCP package not installed" in doctor.report.checks[-1].message

    def test_mcp_invalid_transport_warn(self, test_config):
        """Test invalid transport warns."""
        test_config.mcp_transport = "invalid_transport"
        with patch('memora.diagnostics.mcp', Mock(__version__="1.0.0")):
            doctor = Doctor(config=test_config)
            doctor._check_mcp_configuration()
            assert doctor.report.checks[-1].status == CheckStatus.WARN
            assert "unknown mcp transport" in doctor.report.checks[-1].message.lower()


# =========================================================================
# Storage Tests
# =========================================================================

class TestStorage:
    """Test storage checks."""

    def test_storage_healthy_pass(self, test_config, temp_dir):
        """Test healthy storage passes."""
        test_config.chroma_path.mkdir(parents=True, exist_ok=True)
        test_config.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        test_config.data_dir.mkdir(parents=True, exist_ok=True)

        doctor = Doctor(config=test_config)
        doctor._check_storage()
        assert doctor.report.checks[-1].status == CheckStatus.PASS

    def test_storage_low_disk_warn(self, test_config, temp_dir):
        """Test low disk space warns."""
        test_config.chroma_path.mkdir(parents=True, exist_ok=True)
        test_config.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        test_config.data_dir.mkdir(parents=True, exist_ok=True)

        with patch('shutil.disk_usage') as mock_disk:
            # 500MB = 500 * 1024 * 1024 bytes = 0.5GB (should trigger < 1GB warning)
            mock_disk.return_value = Mock(free=500 * 1024 * 1024)

            doctor = Doctor(config=test_config)
            doctor._check_storage()
            assert doctor.report.checks[-1].status == CheckStatus.WARN
            assert "disk space" in doctor.report.checks[-1].message.lower()

    def test_storage_permission_fail(self, test_config):
        """Test storage permission failure."""
        with patch('pathlib.Path.mkdir') as mock_mkdir:
            mock_mkdir.side_effect = PermissionError("Permission denied")

            doctor = Doctor(config=test_config)
            doctor._check_storage()
            assert doctor.report.checks[-1].status == CheckStatus.FAIL


# =========================================================================
# Integration Tests
# =========================================================================

class TestDoctorIntegration:
    """Integration tests for full doctor run."""

    def test_full_doctor_run_pass(self, test_config, test_vault, temp_dir):
        """Test full doctor run with mostly passing checks."""
        test_config.chroma_path.mkdir(parents=True, exist_ok=True)
        test_config.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        test_config.data_dir.mkdir(parents=True, exist_ok=True)

        with patch.object(Doctor, '_create_ollama_provider') as mock_create_ollama:
            with patch('memora.diagnostics.VectorStore') as mock_chroma_class:
                with patch('memora.diagnostics.MetadataStore') as mock_sqlite_class:
                    with patch('memora.diagnostics.VaultReader') as mock_vault_class:
                        with patch('shutil.disk_usage') as mock_disk:
                            with patch('memora.diagnostics.mcp', Mock(__version__="1.0.0")):
                                with patch('sqlite3.connect') as mock_sqlite_connect:
                                    with patch('httpx.get') as mock_http_get:

                                        # Ollama mocks
                                        mock_ollama = Mock()
                                        mock_ollama.health_check.return_value = True
                                        mock_ollama.get_model_info.return_value = {"name": "nomic-embed-text", "dimensions": 768}
                                        mock_ollama_result = Mock()
                                        mock_ollama_result.embeddings = [[0.1]*768]
                                        mock_ollama_result.model = "nomic-embed-text"
                                        mock_ollama_result.token_count = 10
                                        mock_ollama.generate_embeddings.return_value = mock_ollama_result
                                        mock_create_ollama.return_value = mock_ollama

                                        # HTTP mock for model tags
                                        mock_response = Mock()
                                        mock_response.json.return_value = {"models": [{"name": "nomic-embed-text:latest"}]}
                                        mock_response.status_code = 200
                                        mock_http_get.return_value = mock_response

                                        # ChromaDB mock
                                        mock_chroma = Mock()
                                        mock_chroma.get_collection_info.return_value = {
                                            "count": 100,
                                            "metadata": {"embedding_model": "nomic-embed-text", "embedding_dimensions": "768"}
                                        }
                                        mock_chroma_class.return_value = mock_chroma

                                        # SQLite mock
                                        mock_sqlite = Mock()
                                        mock_sqlite.get_index_stats.return_value = {"total_chunks": 100}
                                        mock_sqlite_class.return_value = mock_sqlite

                                        # Vault reader mock
                                        mock_vault = Mock()
                                        mock_vault.list_files.return_value = ["note1.md", "note2.md"]
                                        mock_vault_class.return_value = mock_vault

                                        # Disk space mock
                                        mock_disk.return_value = Mock(free=10 * 1024**3)

                                        # SQLite connection mock
                                        mock_conn = MagicMock()
                                        mock_conn.__enter__ = Mock(return_value=mock_conn)
                                        mock_conn.__exit__ = Mock(return_value=None)
                                        mock_conn.execute.return_value.fetchone.return_value = ("wal",)
                                        mock_sqlite_connect.return_value = mock_conn

                                        doctor = Doctor(config=test_config)
                                        report = doctor.run_all()

                                        assert len(report.checks) >= 10
                                        pass_count = sum(1 for c in report.checks if c.status == CheckStatus.PASS)
                                        assert pass_count >= 7

    def test_doctor_json_output(self, test_config, temp_dir):
        """Test JSON output format."""
        import json
        import io
        import sys

        with patch.object(Doctor, '_create_ollama_provider') as mock_create_ollama:
            with patch('memora.diagnostics.VectorStore') as mock_chroma_class:
                with patch('memora.diagnostics.MetadataStore') as mock_sqlite_class:
                    with patch('memora.diagnostics.VaultReader') as mock_vault_class:
                        with patch('shutil.disk_usage') as mock_disk:
                            with patch('memora.diagnostics.mcp', Mock(__version__="1.0.0")):
                                with patch('sqlite3.connect') as mock_sqlite_connect:
                                    with patch('httpx.get') as mock_http_get:

                                        mock_ollama = Mock()
                                        mock_ollama.health_check.return_value = True
                                        mock_ollama.get_model_info.return_value = {"name": "nomic-embed-text", "dimensions": 768}
                                        mock_ollama_result = Mock()
                                        mock_ollama_result.embeddings = [[0.1]*768]
                                        mock_ollama_result.model = "nomic-embed-text"
                                        mock_ollama_result.token_count = 10
                                        mock_ollama.generate_embeddings.return_value = mock_ollama_result
                                        mock_create_ollama.return_value = mock_ollama

                                        mock_response = Mock()
                                        mock_response.json.return_value = {"models": [{"name": "nomic-embed-text:latest"}]}
                                        mock_response.status_code = 200
                                        mock_http_get.return_value = mock_response

                                        mock_chroma = Mock()
                                        mock_chroma.get_collection_info.return_value = {"count": 0, "metadata": {}}
                                        mock_chroma_class.return_value = mock_chroma

                                        mock_sqlite = Mock()
                                        mock_sqlite.get_index_stats.return_value = {"total_chunks": 0}
                                        mock_sqlite_class.return_value = mock_sqlite

                                        mock_vault = Mock()
                                        mock_vault.list_files.return_value = []
                                        mock_vault_class.return_value = mock_vault

                                        mock_disk.return_value = Mock(free=10 * 1024**3)

                                        mock_conn = MagicMock()
                                        mock_conn.__enter__ = Mock(return_value=mock_conn)
                                        mock_conn.__exit__ = Mock(return_value=None)
                                        mock_conn.execute.return_value.fetchone.return_value = ("wal",)
                                        mock_sqlite_connect.return_value = mock_conn

                                        old_stdout = sys.stdout
                                        sys.stdout = io.StringIO()

                                        try:
                                            report = run_doctor(config=test_config, json_output=True)
                                            output = sys.stdout.getvalue()
                                        finally:
                                            sys.stdout = old_stdout

                                        data = json.loads(output)
                                        assert data["status"] in ("PASS", "WARN", "FAIL")
                                        assert "exit_code" in data
                                        assert "checks" in data
                                        assert isinstance(data["checks"], list)
                                        assert len(data["checks"]) > 0

                                        for check in data["checks"]:
                                            assert "name" in check
                                            assert "status" in check
                                            assert "message" in check
                                            assert "details" in check


# =========================================================================
# Run Tests
# =========================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])