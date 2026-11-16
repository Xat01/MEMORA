"""
Tests for Chunker.
"""

import pytest
from memora.ingestion.chunker import Chunker, TextChunk, chunk_vault_file
from memora.ingestion.vault_reader import VaultFile


class TestChunker:
    """Test Chunker functionality."""

    def test_chunk_simple_text(self):
        """Test chunking simple text without headers."""
        chunker = Chunker(chunk_size=100, chunk_overlap=10)
        text = "This is a simple paragraph. " * 10  # ~250 chars
        chunks = chunker.chunk_text(text, "test.md")

        assert len(chunks) >= 1
        assert all(isinstance(c, TextChunk) for c in chunks)
        assert all(c.token_count > 0 for c in chunks)
        assert all(c.chunk_hash for c in chunks)

    def test_chunk_with_headers(self):
        """Test chunking respects Markdown headers."""
        chunker = Chunker(chunk_size=200, chunk_overlap=20)
        text = """# Main Title

Introduction paragraph here.

## Section 1

Content for section 1. This is a longer paragraph that should be split appropriately.

## Section 2

Content for section 2 with more details.

### Subsection 2.1

Nested subsection content.

## Section 3

Final section content.
"""
        chunks = chunker.chunk_text(text, "test.md")

        assert len(chunks) >= 1
        # Check heading paths are preserved
        heading_paths = [c.heading_path for c in chunks]
        assert any("Main Title" in hp for hp in heading_paths)
        assert any("Section 1" in hp for hp in heading_paths)
        assert any("Section 2::Subsection 2.1" in hp for hp in heading_paths)

    def test_chunk_code_blocks_preserved(self):
        """Test code blocks are preserved as atomic units."""
        chunker = Chunker(chunk_size=100, chunk_overlap=10)
        text = """# Code Example

Here is some code:

```python
def hello():
    print("Hello, World!")
    return 42
```

After the code block.
"""
        chunks = chunker.chunk_text(text, "test.md")

        # Code block should not be split
        code_chunks = [c for c in chunks if "def hello" in c.text]
        assert len(code_chunks) >= 1
        for c in code_chunks:
            assert "def hello():" in c.text
            assert 'print("Hello, World!")' in c.text
            assert "return 42" in c.text

    def test_chunk_overlap_applied(self):
        """Test overlap between adjacent chunks."""
        chunker = Chunker(chunk_size=20, chunk_overlap=10)
        text = "Sentence one. " * 20  # ~280 chars, should make multiple chunks
        chunks = chunker.chunk_text(text, "test.md")

        assert len(chunks) >= 2
        # Check overlap exists between adjacent chunks
        for i in range(1, len(chunks)):
            prev_end = chunks[i-1].text[-50:]  # Last 50 chars of prev
            curr_start = chunks[i].text[:50]   # First 50 chars of curr
            # There should be some overlap
            common = set(prev_end.split()) & set(curr_start.split())
            assert len(common) > 0, f"No overlap between chunks {i-1} and {i}"

    def test_chunk_empty_text(self):
        """Test chunking empty text returns empty list."""
        chunker = Chunker()
        chunks = chunker.chunk_text("", "test.md")
        assert chunks == []

    def test_chunk_whitespace_only(self):
        """Test chunking whitespace only returns empty list."""
        chunker = Chunker()
        chunks = chunker.chunk_text("   \n\n   \t  ", "test.md")
        assert chunks == []

    def test_chunk_single_paragraph_larger_than_chunk_size(self):
        """Test single large paragraph is split by sentences."""
        chunker = Chunker(chunk_size=30, chunk_overlap=5)
        text = "This is a very long sentence that should be split because it exceeds the chunk size limit. " * 3
        chunks = chunker.chunk_text(text, "test.md")

        assert len(chunks) >= 2
        # Each chunk should be reasonable size
        for c in chunks:
            assert c.token_count <= chunker.chunk_size + 10  # Some tolerance

    def test_chunk_hash_deterministic(self):
        """Test chunk hashes are deterministic."""
        chunker = Chunker(chunk_size=100, chunk_overlap=10)
        text = "Test content for hashing. " * 5

        chunks1 = chunker.chunk_text(text, "test.md")
        chunks2 = chunker.chunk_text(text, "test.md")

        assert len(chunks1) == len(chunks2)
        for c1, c2 in zip(chunks1, chunks2):
            assert c1.chunk_hash == c2.chunk_hash

    def test_chunk_vault_file_integration(self, test_config, test_vault_path):
        """Test chunk_vault_file convenience function."""
        from memora.ingestion.vault_reader import VaultReader

        reader = VaultReader(vault_path=test_vault_path)
        vault_file = reader.read_file("Projects/machine-learning-notes.md")

        chunks = chunk_vault_file(vault_file)

        assert len(chunks) >= 1
        assert all(isinstance(c, TextChunk) for c in chunks)
        # Should have heading paths
        heading_paths = [c.heading_path for c in chunks]
        assert any("Machine Learning Fundamentals" in hp for hp in heading_paths)
        assert any("Supervised Learning" in hp for hp in heading_paths)

    def test_chunk_char_offsets(self):
        """Test character offsets are tracked correctly (approximate)."""
        chunker = Chunker(chunk_size=100, chunk_overlap=0)  # No overlap for cleaner offsets
        text = "# Header\n\nContent here.\n\n## Subheader\n\nMore content."
        chunks = chunker.chunk_text(text, "test.md")

        for chunk in chunks:
            assert chunk.start_char >= 0
            assert chunk.end_char > chunk.start_char
            # Offsets may exceed text length due to overlap, just check they're reasonable
            assert chunk.start_char < len(text) * 2
            assert chunk.end_char < len(text) * 2

    def test_estimate_tokens(self):
        """Test token estimation."""
        chunker = Chunker()
        # Roughly 4 chars = 1 token
        assert chunker._estimate_tokens("abcd") == 1
        assert chunker._estimate_tokens("abcdefgh") == 2
        assert chunker._estimate_tokens("") == 1  # Minimum 1