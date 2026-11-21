"""Models served by Ollama: local ones, or Ollama ":cloud" models."""

import json
import time
from typing import AsyncIterator, List, Optional, Union

import httpx

from ..log import logger
from .base import Message, Provider, ToolCall, Tools


class OllamaProvider(Provider):
    @property
    def label(self) -> str:
        return "Ollama"

    async def stream(
        self, messages: List[Message], tools: Optional[Tools]
    ) -> AsyncIterator[Union[str, ToolCall]]:
        payload = {"model": self.model, "messages": messages, "stream": True}
        if tools:
            payload["tools"] = tools
        logger.info(
            "   → Ollama POST /api/chat model=%s messages=%d tools=%d",
            self.model, len(messages), len(tools or []),
        )
        started = time.perf_counter()
        first = True

        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream(
                "POST", f"{self.settings.ollama_url}/api/chat", json=payload
            ) as response:
                if response.status_code != 200:
                    body = (await response.aread()).decode(errors="replace")
                    raise RuntimeError(f"Ollama returned {response.status_code}: {body}")

                # Ollama streams one JSON object per line.
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    chunk = json.loads(line)
                    if "error" in chunk:
                        raise RuntimeError(chunk["error"])
                    message = chunk.get("message", {})
                    if first and (message.get("content") or message.get("tool_calls")):
                        logger.info("   ← Ollama first output after %.1fs", time.perf_counter() - started)
                        first = False
                    if message.get("content"):
                        yield message["content"]
                    for i, call in enumerate(message.get("tool_calls") or []):
                        fn = call.get("function", {})
                        logger.info("   ← Ollama wants tool %s(%s)", fn.get("name"), json.dumps(fn.get("arguments")))
                        yield ToolCall(
                            id=call.get("id") or f"call_{i}",
                            name=fn.get("name", ""),
                            arguments=fn.get("arguments") or {},
                        )
                    if chunk.get("done"):
                        break

    def assistant_message(self, content: str, calls: List[ToolCall]) -> Message:
        return {
            "role": "assistant",
            "content": content,
            "tool_calls": [{"function": {"name": c.name, "arguments": c.arguments}} for c in calls],
        }

    def tool_message(self, call: ToolCall, result: str) -> Message:
        return {"role": "tool", "tool_name": call.name, "content": result}

    async def is_up(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=3) as client:
                response = await client.get(f"{self.settings.ollama_url}/api/tags")
                return response.status_code == 200
        except httpx.HTTPError as exc:
            logger.warning("   Ollama unreachable at %s (%s)", self.settings.ollama_url, exc)
            return False
