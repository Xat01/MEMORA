"""
MEMORA Hybrid Search

Combines keyword (BM25) and semantic (vector) search using Reciprocal Rank Fusion (RRF).
"""

from dataclasses import dataclass
from typing import Optional, List, Dict, Any

from memora.retrieval.keyword_search import KeywordSearch, KeywordResult
from memora.retrieval.vector_search import VectorSearch, VectorResult
from memora.config import get_config


@dataclass
class SearchResult:
    """Unified search result from hybrid search."""
    chunk_id: str
    content: str
    file_path: str
    chunk_index: int
    heading_path: str
    tags: List[str]
    keyword_rank: Optional[int] = None       # Rank in keyword results (1-based)
    keyword_score: Optional[float] = None    # Normalized keyword score
    vector_rank: Optional[int] = None        # Rank in vector results (1-based)
    vector_score: Optional[float] = None     # Cosine similarity
    rrf_score: float = 0.0                   # Combined RRF score
    source: str = "hybrid"                   # "keyword", "vector", or "hybrid"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "chunk_id": self.chunk_id,
            "content": self.content,
            "file_path": self.file_path,
            "chunk_index": self.chunk_index,
            "heading_path": self.heading_path,
            "tags": self.tags,
            "keyword_rank": self.keyword_rank,
            "keyword_score": self.keyword_score,
            "vector_rank": self.vector_rank,
            "vector_score": self.vector_score,
            "rrf_score": self.rrf_score,
            "source": self.source,
        }


class HybridSearch:
    """
    Hybrid search combining keyword and vector search via RRF.

    Reciprocal Rank Fusion (RRF):
    score = 1/(k + rank_keyword) + 1/(k + rank_vector)

    Where k is a constant (typically 60) that controls the influence
    of lower-ranked results.
    """

    def __init__(self,
                 keyword_search: Optional[KeywordSearch] = None,
                 vector_search: Optional[VectorSearch] = None,
                 rrf_k: Optional[int] = None):
        self.keyword_search = keyword_search or KeywordSearch()
        self.vector_search = vector_search or VectorSearch()
        self.rrf_k = rrf_k or 60

    def search(self, query: str, k: int = 10,
               mode: str = "hybrid",
               file_paths: Optional[List[str]] = None,
               tags: Optional[List[str]] = None) -> List[SearchResult]:
        """
        Perform hybrid search.

        Args:
            query: Search query
            k: Number of results to return
            mode: "hybrid" (default), "keyword", or "vector"
            file_paths: Optional file path filter
            tags: Optional tag filter

        Returns:
            List of SearchResult sorted by combined score
        """
        valid_modes = ("hybrid", "keyword", "vector")
        if mode not in valid_modes:
            raise ValueError(f"Invalid mode: {mode}. Must be one of {valid_modes}")

        if mode == "keyword":
            return self._keyword_only(query, k, file_paths)
        elif mode == "vector":
            return self._vector_only(query, k, file_paths, tags)
        else:
            return self._hybrid(query, k, file_paths, tags)

    def _keyword_only(self, query: str, k: int,
                      file_paths: Optional[List[str]]) -> List[SearchResult]:
        """Keyword-only search."""
        kw_results = self.keyword_search.search(query, k, file_paths)

        results = []
        for rank, kr in enumerate(kw_results, 1):
            results.append(SearchResult(
                chunk_id=kr.chunk_id,
                content=kr.content,
                file_path=kr.file_path,
                chunk_index=0,  # Not available from keyword search
                heading_path=kr.heading_path,
                tags=[],
                keyword_rank=rank,
                keyword_score=kr.score,
                rrf_score=kr.score,
                source="keyword",
            ))
        return results

    def _vector_only(self, query: str, k: int,
                     file_paths: Optional[List[str]],
                     tags: Optional[List[str]]) -> List[SearchResult]:
        """Vector-only search."""
        vec_results = self.vector_search.search(query, k, file_paths, tags)

        results = []
        for rank, vr in enumerate(vec_results, 1):
            tag_list = [t.strip() for t in vr.tags.split(",")] if vr.tags else []
            results.append(SearchResult(
                chunk_id=vr.chunk_id,
                content=vr.content,
                file_path=vr.file_path,
                chunk_index=vr.chunk_index,
                heading_path=vr.heading_path,
                tags=tag_list,
                vector_rank=rank,
                vector_score=vr.similarity,
                rrf_score=vr.similarity,
                source="vector",
            ))
        return results

    def _hybrid(self, query: str, k: int,
                file_paths: Optional[List[str]],
                tags: Optional[List[str]]) -> List[SearchResult]:
        """Full hybrid search with RRF fusion."""
        # Get more results from each for better fusion
        fetch_k = k * 3

        kw_results = self.keyword_search.search(query, fetch_k, file_paths)
        vec_results = self.vector_search.search(query, fetch_k, file_paths, tags)

        # Build rank maps
        kw_ranks = {r.chunk_id: i + 1 for i, r in enumerate(kw_results)}
        vec_ranks = {r.chunk_id: i + 1 for i, r in enumerate(vec_results)}

        # Get all unique chunk IDs
        all_chunk_ids = set(kw_ranks.keys()) | set(vec_ranks.keys())

        # Compute RRF scores
        scored_results = []
        for chunk_id in all_chunk_ids:
            kw_rank = kw_ranks.get(chunk_id)
            vec_rank = vec_ranks.get(chunk_id)

            # RRF formula: 1/(k + rank)
            kw_score = 1.0 / (self.rrf_k + kw_rank) if kw_rank else 0.0
            vec_score = 1.0 / (self.rrf_k + vec_rank) if vec_rank else 0.0
            rrf_score = kw_score + vec_score

            # Get content from whichever result has it
            content = ""
            file_path = ""
            chunk_index = 0
            heading_path = ""
            tags_list = []

            # Prefer vector result for richer metadata
            if chunk_id in vec_ranks:
                vr = vec_results[vec_rank - 1]
                content = vr.content
                file_path = vr.file_path
                chunk_index = vr.chunk_index
                heading_path = vr.heading_path
                tags_list = [t.strip() for t in vr.tags.split(",")] if vr.tags else []
            elif chunk_id in kw_ranks:
                kr = kw_results[kw_rank - 1]
                content = kr.content
                file_path = kr.file_path
                heading_path = kr.heading_path

            scored_results.append(SearchResult(
                chunk_id=chunk_id,
                content=content,
                file_path=file_path,
                chunk_index=chunk_index,
                heading_path=heading_path,
                tags=tags_list,
                keyword_rank=kw_rank,
                keyword_score=kw_results[kw_rank - 1].score if kw_rank else None,
                vector_rank=vec_rank,
                vector_score=vec_results[vec_rank - 1].similarity if vec_rank else None,
                rrf_score=rrf_score,
                source="hybrid",
            ))

        # Sort by RRF score descending
        scored_results.sort(key=lambda r: r.rrf_score, reverse=True)

        return scored_results[:k]

    def search_with_context(self, query: str, k: int = 10,
                           mode: str = "hybrid",
                           context_chars: int = 300) -> List[SearchResult]:
        """
        Search with context snippets.

        For now, returns full content. Could be extended to extract
        snippets around query term matches.
        """
        return self.search(query, k, mode)

    def get_chunk_by_id(self, chunk_id: str) -> Optional[SearchResult]:
        """Retrieve a specific chunk by ID."""
        # Try vector store first (has full metadata)
        vec_data = self.vector_search.vector_store.get([chunk_id])

        if vec_data.get("ids") and vec_data["ids"]:
            metadata = vec_data["metadatas"][0]
            content = vec_data["documents"][0]

            return SearchResult(
                chunk_id=chunk_id,
                content=content,
                file_path=metadata.get("file_path", ""),
                chunk_index=metadata.get("chunk_index", 0),
                heading_path=metadata.get("heading_path", ""),
                tags=[t.strip() for t in metadata.get("tags", "").split(",")] if metadata.get("tags") else [],
                source="direct",
            )
        return None