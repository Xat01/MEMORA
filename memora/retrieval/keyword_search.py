"""
MEMORA Keyword Search

BM25 full-text search using SQLite FTS5.
"""

from dataclasses import dataclass
from typing import Optional, List

from memora.storage.metadata_store import MetadataStore
from memora.config import get_config


@dataclass
class KeywordResult:
    """Result from keyword search."""
    chunk_id: str
    content: str
    heading_path: str
    file_path: str
    rank: float          # BM25 score (lower is better)
    score: float         # Normalized score (0-1, higher is better)


class KeywordSearch:
    """
    Keyword search using SQLite FTS5 BM25 ranking.
    """

    def __init__(self, metadata_store: Optional[MetadataStore] = None):
        self.metadata_store = metadata_store or MetadataStore()

    def search(self, query: str, k: int = 10,
               file_paths: Optional[List[str]] = None) -> List[KeywordResult]:
        """
        Search for query terms in indexed chunks.

        Args:
            query: Search query (supports FTS5 syntax)
            k: Maximum number of results
            file_paths: Optional list of file paths to filter

        Returns:
            List of KeywordResult sorted by relevance
        """
        # Handle empty query
        if not query or not query.strip():
            return []

        # Prepare FTS5 query
        fts_query = self._prepare_query(query)

        # Execute search
        raw_results = self.metadata_store.keyword_search(fts_query, k * 2)  # Get more for filtering

        # Filter by file_paths if provided
        if file_paths:
            file_path_set = set(file_paths)
            raw_results = [r for r in raw_results if r["file_path"] in file_path_set]

        # Limit results
        raw_results = raw_results[:k]

        # Convert to KeywordResult with normalized scores
        results = []
        if raw_results:
            # BM25 scores are positive, lower is better
            # Normalize to 0-1 where 1 is best
            max_rank = max(r["rank"] for r in raw_results)
            min_rank = min(r["rank"] for r in raw_results)
            rank_range = max_rank - min_rank if max_rank != min_rank else 1

            for r in raw_results:
                normalized_score = 1.0 - ((r["rank"] - min_rank) / rank_range)
                results.append(KeywordResult(
                    chunk_id=r["chunk_id"],
                    content=r["content"],
                    heading_path=r["heading_path"] or "",
                    file_path=r["file_path"],
                    rank=r["rank"],
                    score=normalized_score,
                ))

        return results

    def _prepare_query(self, query: str) -> str:
        """
        Prepare query for FTS5.

        FTS5 supports:
        - "term" - exact phrase
        - "term*" - prefix match
        - "term1 term2" - AND (both terms)
        - "term1 OR term2" - OR
        - "term1 NOT term2" - NOT
        - "column:term" - column-specific
        """
        # Simple approach: split on whitespace, add prefix wildcard
        # for better recall
        terms = query.strip().split()
        if not terms:
            return ""

        # If query already contains FTS5 operators, use as-is
        fts_operators = {"AND", "OR", "NOT", "*", '"', ":", "-"}
        if any(op in query for op in fts_operators):
            return query

        # Otherwise, create OR query with prefix matching
        fts_terms = [f"{term}*" for term in terms]
        return " OR ".join(fts_terms)

    def search_with_context(self, query: str, k: int = 10,
                           context_chars: int = 200) -> List[KeywordResult]:
        """
        Search with context snippets around matches.

        Note: FTS5 doesn't directly return match positions,
        so this returns full chunk content. For snippets,
        consider post-processing.
        """
        return self.search(query, k)