"""
MEMORA Ollama Embedding Provider

Local embedding generation via Ollama HTTP API.
"""

import httpx
import logging
from typing import Optional

from memora.config import get_config
from memora.embeddings.base import EmbeddingProvider, EmbeddingResult

# Module logger
logger = logging.getLogger("memora.embeddings.ollama")


class OllamaProvider(EmbeddingProvider):
    """
    Ollama embedding provider for local embeddings.

    Uses Ollama's /api/embeddings endpoint for batch embedding generation.
    Supports explicit OLLAMA_MODE configuration ('host' or 'container')
    with separate validation for each mode.
    """

    def __init__(self, host: Optional[str] = None, model: Optional[str] = None,
                 timeout: float = 120.0, mode: Optional[str] = None,
                 host_fallback: Optional[str] = None):
        if host is None or model is None:
            try:
                self.config = get_config()
            except Exception:
                self.config = None
        else:
            self.config = None

        # Resolve Ollama mode and host
        if self.config:
            self.ollama_mode = mode or self.config.ollama_mode
            self.host_fallback = host_fallback or self.config.ollama_host_fallback
        else:
            self.ollama_mode = mode or "host"
            self.host_fallback = host_fallback

        # Primary host based on mode
        if self.config:
            if self.ollama_mode == "container":
                self.host = host or (self.config.ollama_host or "http://ollama:11434")
            else:
                self.host = host or (self.config.ollama_host or "http://localhost:11434")
            self.model = model or self.config.embedding_model
        else:
            self.host = host or "http://localhost:11434"
            self.model = model or "nomic-embed-text"

        self.timeout = timeout
        self._client: Optional[httpx.Client] = None
        self._model_info: Optional[dict] = None

        # Log configuration
        logger.info(f"OllamaProvider initialized: mode={self.ollama_mode}, host={self.host}, model={self.model}")

    @property
    def provider_name(self) -> str:
        return "ollama"

    @property
    def model_name(self) -> str:
        return self.model

    @property
    def dimensions(self) -> int:
        return self.config.embedding_dimensions if self.config else 768

    @property
    def client(self) -> httpx.Client:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.Client(
                base_url=self.host,
                timeout=self.timeout,
                headers={"Content-Type": "application/json"},
            )
        return self._client

    def generate_embeddings(self, texts: list[str]) -> EmbeddingResult:
        """
        Generate embeddings for a list of texts via Ollama.

        Args:
            texts: List of text strings to embed

        Returns:
            EmbeddingResult with embeddings and metadata
        """
        if not texts:
            return EmbeddingResult(
                embeddings=[],
                model=self.model,
                dimensions=self.dimensions,
                token_count=0,
                provider=self.provider_name,
            )

        embeddings = []
        total_tokens = 0

        # Process in batches
        batch_size = self.batch_size()
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            batch_embeddings = self._embed_batch(batch)
            embeddings.extend(batch_embeddings)
            total_tokens += sum(self.estimate_tokens(t) for t in batch)

        return EmbeddingResult(
            embeddings=embeddings,
            model=self.model,
            dimensions=self.dimensions,
            token_count=total_tokens,
            provider=self.provider_name,
        )

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed a single batch of texts."""
        embeddings = []
        for text in texts:
            response = self.client.post(
                "/api/embeddings",
                json={"model": self.model, "prompt": text},
            )
            response.raise_for_status()
            data = response.json()
            embedding = data.get("embedding")
            if embedding is None:
                raise ValueError(f"No embedding in response: {data}")
            embeddings.append(embedding)
        return embeddings

    def get_model_info(self) -> dict:
        """Get model information from Ollama."""
        if self._model_info is not None:
            return self._model_info

        try:
            response = self.client.post(
                "/api/show",
                json={"name": self.model},
            )
            if response.status_code == 200:
                self._model_info = response.json()
            else:
                self._model_info = {"name": self.model, "error": "model info not available"}
        except Exception as e:
            self._model_info = {"name": self.model, "error": str(e)}

        # Ensure we have dimensions
        self._model_info.setdefault("dimensions", self.dimensions)
        return self._model_info

    def health_check(self) -> bool:
        """Check if Ollama is running and model is available."""
        try:
            response = self.client.get("/api/tags", timeout=5.0)
            if response.status_code != 200:
                return False
            models = response.json().get("models", [])
            return any(m.get("name", "").startswith(self.model) for m in models)
        except Exception:
            return False

    def validate_both_modes(self) -> dict:
        """
        Validate both host and container Ollama endpoints separately.

        Returns:
            Dict with validation results for each mode.
        """
        results = {
            "primary": {"mode": self.ollama_mode, "host": self.host, "valid": False},
            "fallback": {"host": self.host_fallback, "valid": False} if self.host_fallback else None,
        }

        # Validate primary host
        results["primary"]["valid"] = self._validate_host(self.host)

        # Validate fallback host if configured
        if self.host_fallback:
            results["fallback"]["valid"] = self._validate_host(self.host_fallback)

        return results

    def _validate_host(self, host: str) -> bool:
        """Validate a specific Ollama host."""
        try:
            client = httpx.Client(base_url=host, timeout=5.0)
            response = client.get("/api/tags")
            client.close()
            if response.status_code != 200:
                logger.warning(f"Ollama health check failed for {host}: {response.status_code}")
                return False
            models = response.json().get("models", [])
            model_available = any(m.get("name", "").startswith(self.model) for m in models)
            if not model_available:
                logger.warning(f"Model '{self.model}' not found on {host}")
            return model_available
        except Exception as e:
            logger.warning(f"Ollama validation error for {host}: {e}")
            return False

    def pull_model(self) -> bool:
        """Pull the model if not available."""
        try:
            response = self.client.post(
                "/api/pull",
                json={"name": self.model, "stream": False},
                timeout=300.0,
            )
            return response.status_code == 200
        except Exception:
            return False

    def batch_size(self) -> int:
        """Ollama can handle reasonable batch sizes."""
        return 16

    def close(self) -> None:
        """Close HTTP client."""
        if self._client:
            self._client.close()
            self._client = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()