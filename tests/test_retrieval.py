"""
Tests for Retrieval (Keyword, Vector, Hybrid Search).
"""

import pytest
from unittest.mock import Mock, patch, MagicMock

from memora.retrieval.keyword_search import KeywordSearch, KeywordResult
from memora.retrieval.vector_search import VectorSearch, VectorResult
from memora.retrieval.hybrid_search import HybridSearch, SearchResult


class TestKeywordSearch:
    """Test KeywordSearch functionality."""

    def test_prepare_query_simple(self, test_config, temp_dir):
        """Test query preparation for simple queries."""
        from memora.storage.metadata_store import MetadataStore
        store = MetadataStore(db_path=temp_dir / "test.db")
        search = KeywordSearch(metadata_store=store)
        query = search._prepare_query("machine learning")
        assert query == "machine* OR learning*"

    def test_prepare_query_with_operators(self, test_config, temp_dir):
        """Test query preparation preserves FTS5 operators."""
        from memora.storage.metadata_store import MetadataStore
        store = MetadataStore(db_path=temp_dir / "test.db")
        search = KeywordSearch(metadata_store=store)

        # Already has operators
        assert search._prepare_query('"exact phrase"') == '"exact phrase"'
        assert search._prepare_query("term1 AND term2") == "term1 AND term2"
        assert search._prepare_query("term1 OR term2") == "term1 OR term2"
        assert search._prepare_query("term1 NOT term2") == "term1 NOT term2"
        assert search._prepare_query("prefix*") == "prefix*"
        assert search._prepare_query("column:term") == "column:term"

    def test_search_empty_query(self, test_config, temp_dir):
        """Test search with empty query."""
        db_path = temp_dir / "test.db"
        from memora.storage.metadata_store import MetadataStore
        store = MetadataStore(db_path=db_path)

        # Add some FTS data
        store.upsert_fts("chunk1", "test content", "", "test.md")

        search = KeywordSearch(metadata_store=store)
        results = search.search("", k=10)

        assert results == []

    def test_search_with_results(self, test_config, temp_dir):
        """Test keyword search returns ranked results."""
        db_path = temp_dir / "test.db"
        from memora.storage.metadata_store import MetadataStore
        store = MetadataStore(db_path=db_path)

        store.upsert_fts("chunk1", "machine learning fundamentals", "ML", "test.md")
        store.upsert_fts("chunk2", "deep learning neural networks", "DL", "test.md")
        store.upsert_fts("chunk3", "supervised learning classification", "ML", "test.md")

        search = KeywordSearch(metadata_store=store)
        results = search.search("learning", k=10)

        assert len(results) == 3
        for r in results:
            assert isinstance(r, KeywordResult)
            assert r.chunk_id in ["chunk1", "chunk2", "chunk3"]
            assert 0 <= r.score <= 1
            # BM25 rank can be slightly negative due to floating point
            assert r.rank >= -1e-5

    def test_search_with_file_filter(self, test_config, temp_dir):
        """Test keyword search with file path filter."""
        db_path = temp_dir / "test.db"
        from memora.storage.metadata_store import MetadataStore
        store = MetadataStore(db_path=db_path)

        store.upsert_fts("chunk1", "machine learning", "", "a.md")
        store.upsert_fts("chunk2", "deep learning", "", "b.md")

        search = KeywordSearch(metadata_store=store)
        results = search.search("learning", k=10, file_paths=["a.md"])

        assert len(results) == 1
        assert results[0].file_path == "a.md"

    def test_search_normalized_scores(self, test_config, temp_dir):
        """Test that scores are normalized to 0-1."""
        db_path = temp_dir / "test.db"
        from memora.storage.metadata_store import MetadataStore
        store = MetadataStore(db_path=db_path)

        store.upsert_fts("chunk1", "learning learning learning", "", "test.md")
        store.upsert_fts("chunk2", "learning", "", "test.md")

        search = KeywordSearch(metadata_store=store)
        results = search.search("learning", k=10)

        assert len(results) == 2
        # Best match should have score 1.0
        assert results[0].score == 1.0
        # Worst match should have score 0.0
        assert results[-1].score == 0.0


class TestVectorSearch:
    """Test VectorSearch functionality (with mocked embedding provider)."""

    @pytest.fixture
    def mock_provider(self):
        """Create a mock embedding provider."""
        from memora.embeddings.base import EmbeddingProvider, EmbeddingResult
        provider = Mock(spec=EmbeddingProvider)
        provider.provider_name = "mock"
        provider.model_name = "mock-model"
        provider.dimensions = 768
        provider.generate_embeddings.return_value = EmbeddingResult(
            embeddings=[[0.1] * 768],
            model="mock-model",
            dimensions=768,
            token_count=10,
            provider="mock",
        )
        return provider

    @pytest.fixture
    def mock_vector_store(self):
        """Create a mock vector store."""
        store = Mock()
        store.query.return_value = {
            "ids": [["vec1", "vec2"]],
            "documents": [["Doc 1", "Doc 2"]],
            "metadatas": [[
                {"file_path": "a.md", "chunk_index": 0, "heading_path": "H1", "tags": "tag1"},
                {"file_path": "b.md", "chunk_index": 1, "heading_path": "H2", "tags": "tag2"},
            ]],
            "distances": [[0.1, 0.3]],
        }
        return store

    def test_search_basic(self, test_config, mock_provider, mock_vector_store):
        """Test basic vector search."""
        search = VectorSearch(
            vector_store=mock_vector_store,
            embedding_provider=mock_provider,
        )

        results = search.search("test query", k=5)

        assert len(results) == 2
        assert all(isinstance(r, VectorResult) for r in results)
        assert results[0].chunk_id == "vec1"
        assert results[0].similarity == 0.9  # 1 - 0.1
        assert results[1].similarity == 0.7  # 1 - 0.3
        assert results[0].score == results[0].similarity

    def test_search_sorted_by_similarity(self, test_config, mock_provider, mock_vector_store):
        """Test results sorted by similarity descending."""
        search = VectorSearch(
            vector_store=mock_vector_store,
            embedding_provider=mock_provider,
        )

        results = search.search("test query", k=5)

        assert results[0].similarity >= results[1].similarity

    def test_search_with_file_filter(self, test_config, mock_provider, mock_vector_store):
        """Test vector search with file path filter."""
        mock_vector_store.query.return_value = {
            "ids": [["vec1"]],
            "documents": [["Doc 1"]],
            "metadatas": [[{"file_path": "a.md", "chunk_index": 0, "heading_path": "", "tags": ""}]],
            "distances": [[0.1]],
        }

        search = VectorSearch(
            vector_store=mock_vector_store,
            embedding_provider=mock_provider,
        )

        results = search.search("test", k=5, file_paths=["a.md"])

        # Should pass filter to vector store
        call_args = mock_vector_store.query.call_args
        assert call_args[1]["where"] == {"file_path": {"$in": ["a.md"]}}

    def test_search_with_tag_filter(self, test_config, mock_provider, mock_vector_store):
        """Test vector search with tag filter (post-filtering)."""
        mock_vector_store.query.return_value = {
            "ids": [["vec1", "vec2"]],
            "documents": [["Doc 1", "Doc 2"]],
            "metadatas": [[
                {"file_path": "a.md", "chunk_index": 0, "heading_path": "", "tags": "tag1,tag2"},
                {"file_path": "b.md", "chunk_index": 1, "heading_path": "", "tags": "tag3"},
            ]],
            "distances": [[0.1, 0.2]],
        }

        search = VectorSearch(
            vector_store=mock_vector_store,
            embedding_provider=mock_provider,
        )

        results = search.search("test", k=5, tags=["tag1"])

        # Should filter to only tag1
        assert len(results) == 1
        assert results[0].chunk_id == "vec1"

    def test_search_by_embedding(self, test_config, mock_vector_store):
        """Test search with pre-computed embedding."""
        search = VectorSearch(vector_store=mock_vector_store)
        results = search.search_by_embedding([0.1] * 768, k=5)

        assert len(results) == 2

    def test_get_similar_chunks(self, test_config, mock_vector_store):
        """Test finding similar chunks to a reference chunk."""
        mock_vector_store.get.return_value = {
            "embeddings": [[0.1] * 768],
        }

        search = VectorSearch(vector_store=mock_vector_store)
        results = search.get_similar_chunks("vec1", k=3)

        # Should query with the chunk's embedding
        mock_vector_store.get.assert_called_with(["vec1"])


class TestHybridSearch:
    """Test HybridSearch functionality."""

    @pytest.fixture
    def mock_keyword_search(self):
        """Create mock keyword search."""
        kw = Mock(spec=KeywordSearch)
        kw.search.return_value = [
            KeywordResult("chunk1", "content1", "H1", "a.md", 1.0, 1.0),
            KeywordResult("chunk2", "content2", "H2", "b.md", 2.0, 0.5),
        ]
        return kw

    @pytest.fixture
    def mock_vector_search(self):
        """Create mock vector search."""
        vec = Mock(spec=VectorSearch)
        vec.search.return_value = [
            VectorResult("chunk1", "content1", "a.md", 0, "H1", "tag1", 0.1, 0.9, 0.9),
            VectorResult("chunk3", "content3", "c.md", 0, "H3", "tag2", 0.2, 0.8, 0.8),
        ]
        return vec

    def test_hybrid_search_basic(self, mock_keyword_search, mock_vector_search):
        """Test basic hybrid search with RRF."""
        search = HybridSearch(
            keyword_search=mock_keyword_search,
            vector_search=mock_vector_search,
            rrf_k=60,
        )

        results = search.search("test query", k=5)

        assert len(results) == 3  # chunk1, chunk2, chunk3
        assert all(isinstance(r, SearchResult) for r in results)

        # chunk1 appears in both, should have highest RRF score
        chunk1_result = next(r for r in results if r.chunk_id == "chunk1")
        assert chunk1_result.keyword_rank == 1
        assert chunk1_result.vector_rank == 1
        assert chunk1_result.source == "hybrid"

    def test_hybrid_rrf_scoring(self, mock_keyword_search, mock_vector_search):
        """Test RRF score calculation."""
        search = HybridSearch(
            keyword_search=mock_keyword_search,
            vector_search=mock_vector_search,
            rrf_k=60,
        )

        results = search.search("test query", k=5)

        # chunk1: rank 1 in both -> 1/(60+1) + 1/(60+1) = 2/61
        chunk1_result = next(r for r in results if r.chunk_id == "chunk1")
        expected = 1/61 + 1/61
        assert abs(chunk1_result.rrf_score - expected) < 0.001

        # chunk2: rank 2 in keyword only -> 1/(60+2)
        chunk2_result = next(r for r in results if r.chunk_id == "chunk2")
        expected = 1/62
        assert abs(chunk2_result.rrf_score - expected) < 0.001

        # chunk3: rank 1 in vector only -> 1/(60+1)
        chunk3_result = next(r for r in results if r.chunk_id == "chunk3")
        expected = 1/61
        assert abs(chunk3_result.rrf_score - expected) < 0.001

    def test_hybrid_results_sorted_by_rrf(self, mock_keyword_search, mock_vector_search):
        """Test results sorted by RRF score descending."""
        search = HybridSearch(
            keyword_search=mock_keyword_search,
            vector_search=mock_vector_search,
            rrf_k=60,
        )

        results = search.search("test query", k=5)

        for i in range(len(results) - 1):
            assert results[i].rrf_score >= results[i + 1].rrf_score

    def test_keyword_only_mode(self, mock_keyword_search, mock_vector_search):
        """Test keyword-only search mode."""
        search = HybridSearch(
            keyword_search=mock_keyword_search,
            vector_search=mock_vector_search,
        )

        results = search.search("test query", k=5, mode="keyword")

        assert len(results) == 2
        assert all(r.source == "keyword" for r in results)
        assert all(r.vector_rank is None for r in results)

    def test_vector_only_mode(self, mock_keyword_search, mock_vector_search):
        """Test vector-only search mode."""
        search = HybridSearch(
            keyword_search=mock_keyword_search,
            vector_search=mock_vector_search,
        )

        results = search.search("test query", k=5, mode="vector")

        assert len(results) == 2
        assert all(r.source == "vector" for r in results)
        assert all(r.keyword_rank is None for r in results)

    def test_invalid_mode(self, mock_keyword_search, mock_vector_search):
        """Test invalid mode raises error."""
        search = HybridSearch(
            keyword_search=mock_keyword_search,
            vector_search=mock_vector_search,
        )

        with pytest.raises(ValueError, match="Invalid mode"):
            search.search("test", k=5, mode="invalid")

    def test_get_chunk_by_id(self, mock_keyword_search, mock_vector_search):
        """Test retrieving specific chunk by ID."""
        mock_vector_search.vector_store = Mock()
        mock_vector_search.vector_store.get.return_value = {
            "ids": ["chunk1"],
            "documents": ["Full content here"],
            "metadatas": [{
                "file_path": "a.md",
                "chunk_index": 0,
                "heading_path": "H1",
                "tags": "tag1,tag2",
            }],
        }

        search = HybridSearch(
            keyword_search=mock_keyword_search,
            vector_search=mock_vector_search,
        )

        result = search.get_chunk_by_id("chunk1")

        assert result is not None
        assert result.chunk_id == "chunk1"
        assert result.content == "Full content here"
        assert result.file_path == "a.md"
        assert result.tags == ["tag1", "tag2"]
        assert result.source == "direct"