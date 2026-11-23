"""
Test configuration and fixtures.
"""

import tempfile
from pathlib import Path
import pytest

from memora.config import MemoraConfig


@pytest.fixture
def temp_dir():
    """Create a temporary directory."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        yield Path(tmp)


@pytest.fixture
def test_vault_path():
    """Path to the synthetic test vault."""
    return Path(__file__).parent / "fixtures" / "vault"


@pytest.fixture
def test_config(test_vault_path, temp_dir):
    """Create a test configuration."""
    return MemoraConfig(
        vault_path=test_vault_path,
        chroma_path=temp_dir / "chromadb",
        sqlite_path=temp_dir / "memora.db",
        embedding_model="nomic-embed-text",
        embedding_dimensions=768,
        ollama_host="http://localhost:11434",
        chunk_size=256,
        chunk_overlap=25,
    )


@pytest.fixture
def sample_markdown():
    """Sample markdown content for testing."""
    return """---
title: "Test Document"
tags: [test, sample]
author: "Test Author"
---

# Main Heading

Introduction paragraph.

## Section 1

Content for section 1.

### Subsection 1.1

More detailed content.

## Section 2

Final section with a code block:

```python
def hello():
    print("Hello, World!")
```

End of document.
"""


@pytest.fixture
def sample_vault_file(sample_markdown):
    """Parsed vault file fixture."""
    from memora.ingestion.vault_reader import VaultFile
    import frontmatter

    post = frontmatter.loads(sample_markdown)

    return VaultFile(
        path="test.md",
        name="test.md",
        stem="test",
        content=post.content,
        frontmatter=post.metadata,
        tags=["test", "sample"],
        headings=["Main Heading", "Section 1", "Subsection 1.1", "Section 2"],
        size=len(sample_markdown),
        mtime=1700000000000,
    )