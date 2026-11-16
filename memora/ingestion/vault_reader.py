"""
MEMORA Vault Reader

Reads Obsidian vault files via MCP Connector.
Extracts frontmatter, content, and metadata for indexing.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import frontmatter
import re

from memora.config import get_config


@dataclass
class VaultFile:
    """Represents a file in the Obsidian vault."""
    path: str                    # Vault-relative path
    name: str                    # File name with extension
    stem: str                    # File name without extension
    content: str                 # Full file content (markdown)
    frontmatter: dict = field(default_factory=dict)  # Parsed frontmatter
    tags: list[str] = field(default_factory=list)    # Extracted tags
    headings: list[str] = field(default_factory=list) # Heading texts
    size: int = 0                # File size in bytes
    mtime: int = 0               # Modification time (epoch ms)

    @property
    def is_markdown(self) -> bool:
        return self.path.endswith(".md")

    @property
    def content_without_frontmatter(self) -> str:
        """Content with frontmatter removed."""
        if self.frontmatter:
            # Find the end of frontmatter
            parts = self.content.split("---", 2)
            if len(parts) >= 3:
                return parts[2].lstrip("\n")
        return self.content


class VaultReader:
    """
    Reads vault files via MCP Connector.

    Uses the obsidian_my_cyb MCP tools to read vault content.
    In production, this would be called from within an MCP context.
    For standalone use, provide a custom reader function.
    """

    def __init__(self, vault_path: Optional[Path] = None, mcp_read_func=None):
        if vault_path is None:
            try:
                self.config = get_config()
                self.vault_path = self.config.vault_path
            except Exception:
                self.config = None
                self.vault_path = None
        else:
            self.config = None
            self.vault_path = vault_path
        self._mcp_read_func = mcp_read_func

    def set_mcp_reader(self, read_func) -> None:
        """Set the MCP read function (called from within MCP context)."""
        self._mcp_read_func = mcp_read_func

    def read_file(self, vault_relative_path: str) -> Optional[VaultFile]:
        """
        Read a single file from the vault.

        Args:
            vault_relative_path: Path relative to vault root (e.g., "Projects/note.md")

        Returns:
            VaultFile or None if not found
        """
        if self._mcp_read_func:
            return self._read_via_mcp(vault_relative_path)
        else:
            return self._read_local(vault_relative_path)

    def _read_via_mcp(self, path: str) -> Optional[VaultFile]:
        """Read via MCP Connector (requires active MCP context)."""
        try:
            # This expects mcp__obsidian_my_cyb__get_vault_file to be available
            result = self._mcp_read_func(path=path, format="json")
            if result.get("isError"):
                return None

            data = result.get("structuredContent") or {}
            content = data.get("content", "")
            frontmatter_data = data.get("frontmatter", {})
            tags = data.get("tags", [])

            return self._parse_vault_file(path, content, frontmatter_data, tags)
        except Exception:
            return None

    def _read_local(self, path: str) -> Optional[VaultFile]:
        """Read directly from filesystem (for testing/standalone)."""
        full_path = self.vault_path / path
        if not full_path.exists() or not full_path.is_file():
            return None

        try:
            content = full_path.read_text(encoding="utf-8")
            stat = full_path.stat()

            # Parse frontmatter
            post = frontmatter.loads(content)
            frontmatter_data = post.metadata
            content_without_fm = post.content

            # Extract tags from frontmatter and inline
            tags = list(frontmatter_data.get("tags", []))
            inline_tags = re.findall(r'#([a-zA-Z0-9_\-/]+)', content)
            tags.extend(inline_tags)

            # Extract headings
            headings = re.findall(r'^#{1,6}\s+(.+)$', content, re.MULTILINE)

            return VaultFile(
                path=path,
                name=full_path.name,
                stem=full_path.stem,
                content=content_without_fm,
                frontmatter=frontmatter_data,
                tags=list(set(tags)),  # Deduplicate
                headings=headings,
                size=stat.st_size,
                mtime=int(stat.st_mtime * 1000),
            )
        except Exception:
            return None

    def _parse_vault_file(self, path: str, content: str,
                          frontmatter_data: dict, tags: list[str]) -> VaultFile:
        """Parse raw vault file data into VaultFile."""
        # Extract headings from content
        headings = re.findall(r'^#{1,6}\s+(.+)$', content, re.MULTILINE)

        # Get file stat if possible
        full_path = self.vault_path / path
        size = 0
        mtime = 0
        try:
            stat = full_path.stat()
            size = stat.st_size
            mtime = int(stat.st_mtime * 1000)
        except Exception:
            pass

        return VaultFile(
            path=path,
            name=Path(path).name,
            stem=Path(path).stem,
            content=content,
            frontmatter=frontmatter_data,
            tags=list(set(tags)),
            headings=headings,
            size=size,
            mtime=mtime,
        )

    def list_files(self, extensions: Optional[list[str]] = None) -> list[str]:
        """
        List all vault files.

        Args:
            extensions: Filter by extensions (default: [".md"])

        Returns:
            List of vault-relative paths
        """
        if extensions is None:
            extensions = [".md"]

        if self._mcp_read_func:
            # Would use mcp__obsidian_my_cyb__list_vault_files
            # For now, fallback to local
            return self._list_local(extensions)
        else:
            return self._list_local(extensions)

    def _list_local(self, extensions: list[str]) -> list[str]:
        """List files locally."""
        files = []
        for ext in extensions:
            for file_path in self.vault_path.rglob(f"*{ext}"):
                try:
                    rel_path = file_path.relative_to(self.vault_path)
                    files.append(str(rel_path).replace("\\", "/"))
                except ValueError:
                    continue
        return sorted(files)

    def iter_files(self, extensions: Optional[list[str]] = None):
        """Iterate over all vault files, yielding VaultFile objects."""
        for path in self.list_files(extensions):
            vf = self.read_file(path)
            if vf:
                yield vf