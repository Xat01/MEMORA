"""
MEMORA Chunker

Configurable text chunking with Markdown structure awareness.
Respects headers, code blocks, and semantic boundaries.
"""

import re
from dataclasses import dataclass
from typing import Optional

from memora.config import get_config


@dataclass
class TextChunk:
    """Represents a chunk of text with metadata."""
    text: str                          # Chunk content
    chunk_index: int                   # Index within file
    heading_path: str                  # Hierarchical heading path (e.g., "H1::H2::H3")
    start_char: int                    # Start character in original file
    end_char: int                      # End character in original file
    token_count: int                   # Estimated token count
    chunk_hash: str                    # Hash for change detection


class Chunker:
    """
    Markdown-aware text chunker.

    Strategy:
    1. Split by Markdown headers (H1-H6) to preserve structure
    2. Within sections, split by paragraphs then sentences
    3. Preserve code blocks as atomic units
    4. Maintain configurable overlap for context continuity
    """

    # Patterns for Markdown structure
    HEADER_PATTERN = re.compile(r'^(#{1,6})\s+(.+)$', re.MULTILINE)
    CODE_BLOCK_PATTERN = re.compile(r'```[\s\S]*?```', re.MULTILINE)
    PARAGRAPH_PATTERN = re.compile(r'\n\s*\n')
    SENTENCE_PATTERN = re.compile(r'(?<=[.!?])\s+')

    def __init__(self, chunk_size: Optional[int] = None,
                 chunk_overlap: Optional[int] = None):
        # Only load config if we need default values
        if chunk_size is None or chunk_overlap is None:
            try:
                self.config = get_config()
            except Exception:
                self.config = None
        else:
            self.config = None
        self.chunk_size = chunk_size or (self.config.chunk_size if self.config else 512)
        self.chunk_overlap = chunk_overlap or (self.config.chunk_overlap if self.config else 50)

    def chunk_text(self, text: str, file_path: str = "") -> list[TextChunk]:
        """
        Chunk text into overlapping segments.

        Args:
            text: Text to chunk
            file_path: Optional file path for hash generation

        Returns:
            List of TextChunk objects
        """
        if not text or not text.strip():
            return []

        # Step 1: Split by headers to get major sections
        sections = self._split_by_headers(text)

        # Step 2: Chunk each section
        all_chunks = []
        char_offset = 0

        for section_text, heading_path, section_start in sections:
            section_chunks = self._chunk_section(
                section_text, heading_path, char_offset + section_start
            )
            all_chunks.extend(section_chunks)
            char_offset += len(section_text)

        # Step 3: Apply overlap between adjacent chunks
        if self.chunk_overlap > 0:
            all_chunks = self._apply_overlap(all_chunks, text)

        # Step 4: Generate hashes and token counts
        for i, chunk in enumerate(all_chunks):
            chunk.chunk_index = i
            chunk.token_count = self._estimate_tokens(chunk.text)
            chunk.chunk_hash = self._compute_chunk_hash(chunk.text, file_path, i)

        return all_chunks

    def _split_by_headers(self, text: str) -> list[tuple[str, str, int]]:
        """
        Split text by Markdown headers.

        Returns:
            List of (section_text, heading_path, start_char)
        """
        matches = list(self.HEADER_PATTERN.finditer(text))

        if not matches:
            # No headers - treat entire text as one section
            return [(text, "", 0)]

        sections = []
        current_heading_path = ""
        heading_stack = []  # Stack of (level, heading_text)

        for i, match in enumerate(matches):
            header_level = len(match.group(1))
            header_text = match.group(2).strip()
            start_pos = match.start()

            # Update heading stack
            while heading_stack and heading_stack[-1][0] >= header_level:
                heading_stack.pop()
            heading_stack.append((header_level, header_text))
            current_heading_path = "::".join(h[1] for h in heading_stack)

            # Get section text (from this header to next header or end)
            if i + 1 < len(matches):
                end_pos = matches[i + 1].start()
            else:
                end_pos = len(text)

            section_text = text[start_pos:end_pos]
            sections.append((section_text, current_heading_path, start_pos))

        # Handle content before first header
        if matches[0].start() > 0:
            before_first = text[:matches[0].start()]
            sections.insert(0, (before_first, "", 0))

        return sections

    def _chunk_section(self, text: str, heading_path: str, base_offset: int) -> list[TextChunk]:
        """Chunk a single section respecting code blocks."""
        # Extract and protect code blocks
        code_blocks = []
        protected_text = text

        def protect_code(match):
            placeholder = f"__CODE_BLOCK_{len(code_blocks)}__"
            code_blocks.append(match.group(0))
            return placeholder

        protected_text = self.CODE_BLOCK_PATTERN.sub(protect_code, protected_text)

        # Split into paragraphs
        paragraphs = self.PARAGRAPH_PATTERN.split(protected_text)
        paragraphs = [p.strip() for p in paragraphs if p.strip()]

        # Build chunks from paragraphs
        chunks = []
        current_chunk = ""
        current_start = 0
        chunk_start_offset = base_offset

        for para in paragraphs:
            # Restore code blocks in paragraph
            para_restored = para
            for i, code in enumerate(code_blocks):
                placeholder = f"__CODE_BLOCK_{i}__"
                if placeholder in para_restored:
                    para_restored = para_restored.replace(placeholder, code)

            para_tokens = self._estimate_tokens(para_restored)

            # If single paragraph exceeds chunk_size, split by sentences
            if para_tokens > self.chunk_size:
                if current_chunk:
                    chunks.append(self._make_chunk(current_chunk, heading_path, chunk_start_offset))
                    current_chunk = ""

                sentence_chunks = self._split_by_sentences(para_restored, heading_path,
                                                            base_offset + current_start)
                chunks.extend(sentence_chunks)
                current_start += len(para) + 2  # +2 for \n\n
                chunk_start_offset = base_offset + current_start
                continue

            # Check if adding this paragraph exceeds chunk size
            test_chunk = current_chunk + ("\n\n" if current_chunk else "") + para_restored
            test_tokens = self._estimate_tokens(test_chunk)

            if test_tokens > self.chunk_size and current_chunk:
                # Finalize current chunk
                chunks.append(self._make_chunk(current_chunk, heading_path, chunk_start_offset))
                current_chunk = para_restored
                chunk_start_offset = base_offset + current_start
            else:
                current_chunk = test_chunk

            current_start += len(para) + 2

        # Add final chunk
        if current_chunk:
            chunks.append(self._make_chunk(current_chunk, heading_path, chunk_start_offset))

        return chunks

    def _split_by_sentences(self, text: str, heading_path: str, base_offset: int) -> list[TextChunk]:
        """Split text by sentences when it exceeds chunk size."""
        sentences = self.SENTENCE_PATTERN.split(text)
        sentences = [s.strip() for s in sentences if s.strip()]

        chunks = []
        current_chunk = ""
        chunk_start = base_offset

        for sent in sentences:
            test_chunk = current_chunk + (" " if current_chunk else "") + sent
            test_tokens = self._estimate_tokens(test_chunk)

            if test_tokens > self.chunk_size and current_chunk:
                chunks.append(self._make_chunk(current_chunk, heading_path, chunk_start))
                current_chunk = sent
                chunk_start = base_offset + text.index(sent)
            else:
                current_chunk = test_chunk

        if current_chunk:
            chunks.append(self._make_chunk(current_chunk, heading_path, chunk_start))

        return chunks

    def _make_chunk(self, text: str, heading_path: str, start_offset: int) -> TextChunk:
        """Create a TextChunk from text."""
        end_offset = start_offset + len(text)
        return TextChunk(
            text=text,
            chunk_index=0,  # Will be set later
            heading_path=heading_path,
            start_char=start_offset,
            end_char=end_offset,
            token_count=0,  # Will be set later
            chunk_hash="",  # Will be set later
        )

    def _apply_overlap(self, chunks: list[TextChunk], full_text: str) -> list[TextChunk]:
        """Apply overlap between adjacent chunks."""
        if len(chunks) <= 1:
            return chunks

        overlapped = [chunks[0]]

        for i in range(1, len(chunks)):
            prev_chunk = chunks[i - 1]
            curr_chunk = chunks[i]

            # Get overlap text from end of previous chunk
            overlap_text = self._get_overlap_text(prev_chunk.text)

            if overlap_text:
                # Prepend overlap to current chunk
                new_text = overlap_text + "\n\n" + curr_chunk.text
                new_start = max(0, curr_chunk.start_char - len(overlap_text) - 2)

                overlapped.append(TextChunk(
                    text=new_text,
                    chunk_index=0,  # Will be reset
                    heading_path=curr_chunk.heading_path,
                    start_char=new_start,
                    end_char=curr_chunk.end_char,
                    token_count=0,
                    chunk_hash="",
                ))
            else:
                overlapped.append(curr_chunk)

        return overlapped

    def _get_overlap_text(self, text: str) -> str:
        """Extract overlap text from end of chunk (last N tokens worth)."""
        # Rough: take last ~overlap tokens worth of characters
        overlap_chars = self.chunk_overlap * 4  # ~4 chars per token
        if len(text) <= overlap_chars:
            return text

        # Try to break at sentence boundary
        overlap_region = text[-overlap_chars:]
        sentences = self.SENTENCE_PATTERN.split(overlap_region)
        if len(sentences) > 1:
            return sentences[-1]  # Last complete sentence in overlap region
        return overlap_region

    def _estimate_tokens(self, text: str) -> int:
        """Estimate token count (rough: 4 chars = 1 token)."""
        return max(1, len(text) // 4)

    def _compute_chunk_hash(self, text: str, file_path: str, chunk_index: int) -> str:
        """Compute hash for change detection."""
        import hashlib
        content = f"{file_path}:{chunk_index}:{text}"
        return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


def chunk_vault_file(vault_file, chunker: Optional[Chunker] = None) -> list[TextChunk]:
    """
    Convenience function to chunk a VaultFile.

    Args:
        vault_file: VaultFile object from vault_reader
        chunker: Optional Chunker instance (creates default if not provided)

    Returns:
        List of TextChunk objects
    """
    if chunker is None:
        chunker = Chunker()
    return chunker.chunk_text(vault_file.content_without_frontmatter, vault_file.path)