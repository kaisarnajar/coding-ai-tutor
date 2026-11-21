"""What every model provider must offer, so the chat code works with any of them."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, AsyncIterator, Dict, List, Optional, Union

from ..config import Settings

Message = Dict[str, Any]
Tools = List[Dict[str, Any]]  # OpenAI-style {"type": "function", "function": {...}}


@dataclass
class ToolCall:
    """One tool the model asked to run."""

    id: str
    name: str
    arguments: Dict[str, Any]


class Provider(ABC):
    """A place that serves chat models (Ollama, OpenRouter, ...)."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.model = settings.llm_model

    @property
    @abstractmethod
    def label(self) -> str:
        """Short name for logs, e.g. "Ollama" or "API openrouter.ai"."""

    @abstractmethod
    def stream(
        self, messages: List[Message], tools: Optional[Tools]
    ) -> AsyncIterator[Union[str, ToolCall]]:
        """Send the conversation to the model.

        Yields reply text piece by piece, then any ToolCall the model asked for.
        """

    @abstractmethod
    def assistant_message(self, content: str, calls: List[ToolCall]) -> Message:
        """The model's tool request, in this provider's message format."""

    @abstractmethod
    def tool_message(self, call: ToolCall, result: str) -> Message:
        """A tool's result, in this provider's message format."""

    @abstractmethod
    async def is_up(self) -> bool:
        """True if the provider answers."""
