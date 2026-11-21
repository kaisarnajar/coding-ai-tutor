"""Chat models. Which one answers is set by LLM_PROVIDER and LLM_MODEL in backend/.env."""

from ..config import Settings
from .base import Provider, ToolCall
from .ollama import OllamaProvider
from .openai_compat import OpenAICompatProvider

PROVIDERS = {
    "ollama": OllamaProvider,
    "openai": OpenAICompatProvider,
}


def get_provider(settings: Settings) -> Provider:
    return PROVIDERS[settings.llm_provider](settings)


__all__ = ["Provider", "ToolCall", "get_provider"]
