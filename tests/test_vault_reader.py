"""
Tests for VaultReader.
"""

import pytest
from memora.ingestion.vault_reader import VaultReader, VaultFile


class TestVaultReader:
    """Test VaultReader functionality."""

    def test_list_files(self, test_config, test_vault_path):
        """Test listing vault files."""
        reader = VaultReader(vault_path=test_vault_path)
        files = reader.list_files([".md"])

        assert len(files) >= 6  # At least our test files
        assert all(f.endswith(".md") for f in files)
        assert "Projects/machine-learning-notes.md" in files
        assert "Projects/web-development.md" in files
        assert "Areas/productivity.md" in files
        assert "Resources/api-reference.md" in files
        assert "Resources/database-design.md" in files
        assert "Archive/old-notes.md" in files
        assert "edge-cases.md" in files

    def test_read_file_basic(self, test_config, test_vault_path):
        """Test reading a basic markdown file."""
        reader = VaultReader(vault_path=test_vault_path)
        vault_file = reader.read_file("Projects/machine-learning-notes.md")

        assert vault_file is not None
        assert vault_file.path == "Projects/machine-learning-notes.md"
        assert vault_file.name == "machine-learning-notes.md"
        assert vault_file.stem == "machine-learning-notes"
        assert "# Machine Learning Fundamentals" in vault_file.content
        assert vault_file.frontmatter.get("title") == "Machine Learning Fundamentals"
        assert "ml" in vault_file.tags
        assert "fundamentals" in vault_file.tags
        assert "Machine Learning Fundamentals" in vault_file.headings
        assert "Supervised Learning" in vault_file.headings
        assert "Classification" in vault_file.headings

    def test_read_file_with_code_blocks(self, test_config, test_vault_path):
        """Test reading file with code blocks."""
        reader = VaultReader(vault_path=test_vault_path)
        vault_file = reader.read_file("Projects/web-development.md")

        assert vault_file is not None
        assert "useLocalStorage" in vault_file.content
        assert "localStorage.setItem" in vault_file.content
        assert "web" in vault_file.tags
        assert "frontend" in vault_file.tags

    def test_read_file_unicode(self, test_config, test_vault_path):
        """Test reading file with unicode content."""
        reader = VaultReader(vault_path=test_vault_path)
        vault_file = reader.read_file("edge-cases.md")

        assert vault_file is not None
        assert "中文内容测试" in vault_file.content
        assert "🎉" in vault_file.content
        assert "日本語のテスト" in vault_file.content

    def test_read_nonexistent_file(self, test_config, test_vault_path):
        """Test reading a non-existent file returns None."""
        reader = VaultReader(vault_path=test_vault_path)
        vault_file = reader.read_file("nonexistent.md")

        assert vault_file is None

    def test_iter_files(self, test_config, test_vault_path):
        """Test iterating over vault files."""
        reader = VaultReader(vault_path=test_vault_path)
        files = list(reader.iter_files([".md"]))

        assert len(files) >= 6
        assert all(isinstance(f, VaultFile) for f in files)
        assert all(f.is_markdown for f in files)

    def test_content_without_frontmatter(self, test_config, test_vault_path):
        """Test content_without_frontmatter property."""
        reader = VaultReader(vault_path=test_vault_path)
        vault_file = reader.read_file("Projects/machine-learning-notes.md")

        assert vault_file.frontmatter
        assert "title" in vault_file.frontmatter
        # Frontmatter should be stripped from content_without_frontmatter
        assert "title:" not in vault_file.content_without_frontmatter
        assert "Machine Learning Fundamentals" in vault_file.content_without_frontmatter

    def test_complex_frontmatter(self, test_config, test_vault_path):
        """Test reading complex frontmatter with nested objects."""
        reader = VaultReader(vault_path=test_vault_path)
        vault_file = reader.read_file("edge-cases.md")

        assert vault_file.frontmatter.get("complex_object") is not None
        assert vault_file.frontmatter["complex_object"]["nested"] is True
        assert vault_file.frontmatter["complex_object"]["array"] == [1, 2, 3]

    def test_tags_extraction(self, test_config, test_vault_path):
        """Test tag extraction from frontmatter and inline."""
        reader = VaultReader(vault_path=test_vault_path)
        vault_file = reader.read_file("Resources/api-reference.md")

        assert "api" in vault_file.tags
        assert "reference" in vault_file.tags
        assert "rest" in vault_file.tags
        assert "graphql" in vault_file.tags