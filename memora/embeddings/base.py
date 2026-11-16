"""
MEMORA Embedding Provider Base Class

Abstract base class for embedding providers to allow swapping
between Ollama, OpenAI, Cohere, local transformers, etc.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class EmbeddingResult:
    """Result of embedding generation."""
    embeddings: list[list[float]]
    model: str
    dimensions: int
    token_count: int
    provider: str


class EmbeddingProvider(ABC):
    """
    Abstract base class for embedding providers.

    Implementations should provide:
    - generate_embeddings: Batch embedding generation
    - get_model_info: Model metadata
    - health_check: Provider availability check
    """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Unique provider identifier."""
        pass

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Model name/identifier."""
        pass

    @property
    @abstractmethod
    def dimensions(self) -> int:
        """Embedding output dimensions."""
        pass

    @abstractmethod
    def generate_embeddings(self, texts: list[str]) -> EmbeddingResult:
        """
        Generate embeddings for a list of texts.

        Args:
            texts: List of text strings to embed

        Returns:
            EmbeddingResult with embeddings and metadata
        """
        pass

    @abstractmethod
    def get_model_info(self) -> dict:
        """
        Get model information.

        Returns:
            Dict with model metadata (name, version, dimensions, etc.)
        """
        pass

    @abstractmethod
    def health_check(self) -> bool:
        """
        Check if provider is available and healthy.

        Returns:
            True if provider is ready, False otherwise
        """
        pass

    def estimate_tokens(self, text: str) -> int:
        """
        Rough token estimation (4 chars ≈ 1 token for English).
        Override for provider-specific tokenization.
        """
        return len(text) // 4

    def batch_size(self) -> int:
        """Recommended batch size for this provider."""
        return 32