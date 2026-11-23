"""
MEMORA OpenAI-Compatible Embedding Provider

Works with any OpenAI-compatible embedding API:
- OpenAI (api.openai.com)
- Azure OpenAI
- Together AI, Fireworks, Anyscale, etc.
- Local servers (vLLM, text-embeddings-inference, LiteLLM, etc.)
"""

import httpx
from typing import Optional

from memora.embeddings.base import EmbeddingProvider, EmbeddingResult


class OpenAIProvider(EmbeddingProvider):
    """
    OpenAI-compatible embedding provider.

    Works with any API that implements the /v1/embeddings endpoint:
    - OpenAI, Azure OpenAI, Together AI, Fireworks, Anyscale
    - Self-hosted: vLLM, text-embeddings-inference, LiteLLM, LocalAI

    Configure via environment variables:
        EMBEDDING_PROVIDER=openai
        EMBEDDING_API_KEY=sk-...
        EMBEDDING_API_BASE=https://api.openai.com/v1
        EMBEDDING_MODEL=text-embedding-3-small
        EMBEDDING_DIMENSIONS=1536
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_base: Optional[str] = None,
        model: Optional[str] = None,
        dimensions: Optional[int] = None,
        timeout: float = 60.0,
    ):
        if api_key is None or api_base is None or model is None:
            try:
                from memora.config import get_config
                config = get_config()
                self._api_key = api_key or config.embedding_api_key or ""
                self._api_base = api_base or config.embedding_api_base or "https://api.openai.com/v1"
                self._model = model or config.embedding_model
                self._dimensions = dimensions or config.embedding_dimensions
            except Exception:
                self._api_key = api_key or ""
                self._api_base = api_base or "https://api.openai.com/v1"
                self._model = model or "text-embedding-3-small"
                self._dimensions = dimensions or 1536
        else:
            self._api_key = api_key
            self._api_base = api_base.rstrip("/")
            self._model = model
            self._dimensions = dimensions or 1536

        self.timeout = timeout
        self._client: Optional[httpx.Client] = None

    @property
    def provider_name(self) -> str:
        return "openai"

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def dimensions(self) -> int:
        return self._dimensions

    @property
    def client(self) -> httpx.Client:
        """Get or create HTTP client."""
        if self._client is None:
            headers = {"Content-Type": "application/json"}
            if self._api_key:
                headers["Authorization"] = f"Bearer {self._api_key}"
            self._client = httpx.Client(
                base_url=self._api_base,
                timeout=self.timeout,
                headers=headers,
            )
        return self._client

    def generate_embeddings(self, texts: list[str]) -> EmbeddingResult:
        """Generate embeddings via OpenAI-compatible API."""
        if not texts:
            return EmbeddingResult(
                embeddings=[],
                model=self._model,
                dimensions=self._dimensions,
                token_count=0,
                provider=self.provider_name,
            )

        embeddings = []
        total_tokens = 0

        # Process in batches
        bs = self.batch_size()
        for i in range(0, len(texts), bs):
            batch = texts[i:i + bs]
            batch_result = self._embed_batch(batch)
            embeddings.extend(batch_result["embeddings"])
            total_tokens += batch_result["tokens"]

        return EmbeddingResult(
            embeddings=embeddings,
            model=self._model,
            dimensions=self._dimensions,
            token_count=total_tokens,
            provider=self.provider_name,
        )

    def _embed_batch(self, texts: list[str]) -> dict:
        """Embed a batch of texts."""
        payload = {
            "model": self._model,
            "input": texts,
        }

        response = self.client.post("/embeddings", json=payload)
        response.raise_for_status()
        data = response.json()

        # Sort by index to ensure correct ordering
        sorted_data = sorted(data["data"], key=lambda x: x["index"])
        embeddings = [item["embedding"] for item in sorted_data]
        tokens = data.get("usage", {}).get("total_tokens", sum(len(t) // 4 for t in texts))

        return {"embeddings": embeddings, "tokens": tokens}

    def get_model_info(self) -> dict:
        """Get model information."""
        return {
            "name": self._model,
            "provider": self.provider_name,
            "dimensions": self._dimensions,
            "api_base": self._api_base,
        }

    def health_check(self) -> bool:
        """Check if the API is reachable."""
        try:
            # Try a minimal embedding request
            response = self.client.post(
                "/embeddings",
                json={"model": self._model, "input": ["test"]},
                timeout=10.0,
            )
            return response.status_code == 200
        except Exception:
            return False

    def batch_size(self) -> int:
        """OpenAI supports large batches."""
        return 64

    def close(self) -> None:
        """Close HTTP client."""
        if self._client:
            self._client.close()
            self._client = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
