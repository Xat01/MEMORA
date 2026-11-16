"""
MEMORA Embeddings Module

Provider abstraction for embedding generation with Ollama as default.
"""

from memora.embeddings.base import EmbeddingProvider, EmbeddingResult
from memora.embeddings.ollama_provider import OllamaProvider

__all__ = [
    "EmbeddingProvider",
    "EmbeddingResult",
    "OllamaProvider",
]