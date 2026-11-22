"""
MEMORA Embeddings Module

Provider abstraction for embedding generation.
Built-in providers: Ollama (local), OpenAI-compatible (any API).
"""

from memora.embeddings.base import EmbeddingProvider, EmbeddingResult
from memora.embeddings.ollama_provider import OllamaProvider
from memora.embeddings.openai_provider import OpenAIProvider

__all__ = [
    "EmbeddingProvider",
    "EmbeddingResult",
    "OllamaProvider",
    "OpenAIProvider",
    "create_provider",
    "get_default_provider",
]


def get_default_provider(**kwargs) -> EmbeddingProvider:
    """Create the configured default embedding provider from config."""
    try:
        from memora.config import get_config
        config = get_config()
        provider_name = config.embedding_provider or "ollama"
        return create_provider(provider_name, **kwargs)
    except Exception:
        return OllamaProvider(**kwargs)


def create_provider(provider_name: str = "ollama", **kwargs) -> EmbeddingProvider:
    """Factory: create an embedding provider by name.

    Args:
        provider_name: 'ollama', 'openai', or a fully-qualified class name
                       (e.g., 'mypackage.MyProvider')
        **kwargs: Passed to the provider constructor

    Returns:
        An EmbeddingProvider instance
    """
    if provider_name == "ollama":
        return OllamaProvider(**kwargs)
    elif provider_name == "openai":
        return OpenAIProvider(**kwargs)
    else:
        # Try importing a custom provider class
        try:
            module_path, class_name = provider_name.rsplit(".", 1)
            import importlib
            module = importlib.import_module(module_path)
            cls = getattr(module, class_name)
            if not issubclass(cls, EmbeddingProvider):
                raise TypeError(f"{provider_name} is not an EmbeddingProvider subclass")
            return cls(**kwargs)
        except (ValueError, ImportError, AttributeError) as e:
            raise ValueError(
                f"Unknown embedding provider: '{provider_name}'. "
                f"Use 'ollama', 'openai', or a fully-qualified class name. Error: {e}"
            )
