from src.providers.base import LLMError, LLMProvider
from src.providers.mock import MockLLMProvider
from src.providers.ollama import OllamaProvider

PROVIDERS = ("ollama", "mock")


def provider_from_config(config) -> LLMProvider:
    """Build the provider named by LLM_PROVIDER. There is no fallback between providers."""
    name = str(getattr(config, "LLM_PROVIDER", "ollama") or "ollama").strip().lower()
    if name == "mock":
        return MockLLMProvider()
    if name == "ollama":
        return OllamaProvider(
            getattr(config, "OLLAMA_BASE_URL", ""),
            getattr(config, "OLLAMA_EMBED_MODEL", ""),
            getattr(config, "OLLAMA_CHAT_MODEL", ""),
        )
    raise ValueError(f"LLM_PROVIDER must be one of {', '.join(PROVIDERS)}, not {name!r}.")


__all__ = ["LLMError", "LLMProvider", "MockLLMProvider", "OllamaProvider", "PROVIDERS", "provider_from_config"]
