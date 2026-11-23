"""
Tests for Embedding Provider.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock

from memora.embeddings.base import EmbeddingProvider, EmbeddingResult
from memora.embeddings.ollama_provider import OllamaProvider


class MockEmbeddingProvider(EmbeddingProvider):
    """Mock provider for testing base class."""

    @property
    def provider_name(self) -> str:
        return "mock"

    @property
    def model_name(self) -> str:
        return "mock-model"

    @property
    def dimensions(self) -> int:
        return 384

    def generate_embeddings(self, texts: list[str]) -> EmbeddingResult:
        embeddings = [[0.1] * 384 for _ in texts]
        return EmbeddingResult(
            embeddings=embeddings,
            model=self.model_name,
            dimensions=self.dimensions,
            token_count=sum(len(t) // 4 for t in texts),
            provider=self.provider_name,
        )

    def get_model_info(self) -> dict:
        return {"name": self.model_name, "dimensions": self.dimensions}

    def health_check(self) -> bool:
        return True


class TestEmbeddingProviderBase:
    """Test abstract EmbeddingProvider base class."""

    def test_abstract_methods_enforced(self):
        """Test that abstract methods must be implemented."""
        with pytest.raises(TypeError):
            EmbeddingProvider()

    def test_mock_provider_works(self):
        """Test mock provider implementation works."""
        provider = MockEmbeddingProvider()
        result = provider.generate_embeddings(["test", "another"])

        assert isinstance(result, EmbeddingResult)
        assert len(result.embeddings) == 2
        assert len(result.embeddings[0]) == 384
        assert result.model == "mock-model"
        assert result.dimensions == 384
        assert result.provider == "mock"

    def test_estimate_tokens_default(self):
        """Test default token estimation."""
        provider = MockEmbeddingProvider()
        assert provider.estimate_tokens("abcd") == 1
        assert provider.estimate_tokens("abcdefghijkl") == 3

    def test_batch_size_default(self):
        """Test default batch size."""
        provider = MockEmbeddingProvider()
        assert provider.batch_size() == 32


class TestOllamaProvider:
    """Test OllamaProvider (with mocked HTTP)."""

    @pytest.fixture
    def mock_httpx(self):
        """Mock httpx client."""
        with patch("memora.embeddings.ollama_provider.httpx.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value = mock_client
            yield mock_client

    def test_initialization(self, test_config):
        """Test provider initialization."""
        provider = OllamaProvider(
            host="http://localhost:11434",
            model="test-model"
        )
        assert provider.host == "http://localhost:11434"
        assert provider.model == "test-model"
        assert provider.provider_name == "ollama"
        assert provider.model_name == "test-model"
        assert provider.dimensions == 768

    def test_generate_embeddings_success(self, test_config, mock_httpx):
        """Test successful embedding generation using modern batch endpoint."""
        # Mock batch response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"embeddings": [[0.1] * 768, [0.2] * 768]}
        mock_response.raise_for_status = MagicMock()
        mock_httpx.post.return_value = mock_response

        provider = OllamaProvider(host="http://localhost:11434", model="test-model")
        result = provider.generate_embeddings(["text 1", "text 2"])

        assert len(result.embeddings) == 2
        assert len(result.embeddings[0]) == 768
        assert result.model == "test-model"
        assert result.provider == "ollama"
        assert mock_httpx.post.call_count == 1  # 1 single batch call for all texts

    def test_generate_embeddings_legacy_fallback(self, test_config, mock_httpx):
        """Test fallback to legacy endpoint when batch endpoint is unsupported."""
        def mock_post(url, **kwargs):
            resp = MagicMock()
            if url == "/api/embed":
                resp.status_code = 404
                resp.raise_for_status.side_effect = Exception("404 Not Found")
                return resp
            resp.status_code = 200
            resp.json.return_value = {"embedding": [0.1] * 768}
            resp.raise_for_status = MagicMock()
            return resp

        mock_httpx.post.side_effect = mock_post

        provider = OllamaProvider(host="http://localhost:11434", model="test-model")
        result = provider.generate_embeddings(["text 1", "text 2"])

        assert len(result.embeddings) == 2
        assert len(result.embeddings[0]) == 768
        assert mock_httpx.post.call_count == 3  # 1 attempt to /api/embed + 2 calls to /api/embeddings

    def test_generate_embeddings_empty_list(self, test_config, mock_httpx):
        """Test embedding generation with empty list."""
        provider = OllamaProvider()
        result = provider.generate_embeddings([])

        assert result.embeddings == []
        assert result.token_count == 0
        mock_httpx.post.assert_not_called()

    def test_embed_batch_error_handling(self, test_config, mock_httpx):
        """Test error handling in _embed_batch."""
        mock_response = MagicMock()
        mock_response.json.return_value = {}  # No embedding key
        mock_response.raise_for_status = MagicMock()
        mock_httpx.post.return_value = mock_response

        provider = OllamaProvider()
        with pytest.raises(ValueError, match="No embedding in response"):
            provider._embed_batch(["test"])

    def test_health_check_success(self, test_config, mock_httpx):
        """Test health check when Ollama is available."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "models": [{"name": "nomic-embed-text:latest"}]
        }
        mock_httpx.get.return_value = mock_response

        provider = OllamaProvider(model="nomic-embed-text")
        assert provider.health_check() is True

    def test_health_check_model_not_found(self, test_config, mock_httpx):
        """Test health check when model not available."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "models": [{"name": "other-model:latest"}]
        }
        mock_httpx.get.return_value = mock_response

        provider = OllamaProvider(model="nomic-embed-text")
        assert provider.health_check() is False

    def test_health_check_connection_error(self, test_config, mock_httpx):
        """Test health check on connection error."""
        mock_httpx.get.side_effect = Exception("Connection refused")

        provider = OllamaProvider()
        assert provider.health_check() is False

    def test_get_model_info(self, test_config, mock_httpx):
        """Test getting model info."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "name": "nomic-embed-text",
            "size": 1000000,
            "digest": "abc123"
        }
        mock_httpx.post.return_value = mock_response

        provider = OllamaProvider()
        info = provider.get_model_info()

        assert info["name"] == "nomic-embed-text"
        assert "dimensions" in info

    def test_pull_model_success(self, test_config, mock_httpx):
        """Test pulling model."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_httpx.post.return_value = mock_response

        provider = OllamaProvider()
        assert provider.pull_model() is True

    def test_context_manager(self, test_config, mock_httpx):
        """Test context manager closes client."""
        provider = OllamaProvider()
        provider.__enter__()
        provider.__exit__(None, None, None)
        # Client should be closed
        assert provider._client is None