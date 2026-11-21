"""Models behind any OpenAI-compatible API: OpenRouter, OpenAI, Groq, LM Studio, vLLM, ...

They all accept POST {API_BASE_URL}/chat/completions with the same request and
stream the reply as Server-Sent Events ("data: {...}" lines, ending with "data: [DONE]").
"""

import json
import time
from typing import Any, AsyncIterator, Dict, List, Optional, Union
from urllib.parse import urlparse

import httpx

from ..log import logger
from .base import Message, Provider, ToolCall, Tools


class OpenAICompatProvider(Provider):
    @property
    def base_url(self) -> str:
        return self.settings.api_base_url.rstrip("/")

    @property
    def label(self) -> str:
        return f"API {urlparse(self.base_url).netloc}"

    def _headers(self) -> Dict[str, str]:
        # Local servers (LM Studio, vLLM, ...) usually need no key.
        if self.settings.api_key:
            return {"Authorization": f"Bearer {self.settings.api_key}"}
        return {}

    async def stream(
        self, messages: List[Message], tools: Optional[Tools]
    ) -> AsyncIterator[Union[str, ToolCall]]:
        payload: Dict[str, Any] = {"model": self.model, "messages": messages, "stream": True}
        if tools:
            payload["tools"] = tools
        logger.info(
            "   → %s POST /chat/completions model=%s messages=%d tools=%d",
            self.label, self.model, len(messages), len(tools or []),
        )
        started = time.perf_counter()
        first = True
        # Tool calls arrive in fragments (name and arguments split over many chunks),
        # keyed by their index; they are put together here and returned at the end.
        partial: Dict[int, Dict[str, str]] = {}

        async with httpx.AsyncClient(timeout=httpx.Timeout(10, read=None)) as client:
            async with client.stream(
                "POST", f"{self.base_url}/chat/completions", json=payload, headers=self._headers()
            ) as response:
                if response.status_code != 200:
                    body = (await response.aread()).decode(errors="replace")
                    raise RuntimeError(f"{self.label} returned {response.status_code}: {body}")

                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue  # blank lines and ": keep-alive" comments
                    data = line[len("data:"):].strip()
                    if data == "[DONE]":
                        break
                    chunk = json.loads(data)
                    if "error" in chunk:
                        error = chunk["error"]
                        raise RuntimeError(error.get("message", error) if isinstance(error, dict) else error)
                    choices = chunk.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}

                    if first and (delta.get("content") or delta.get("tool_calls")):
                        logger.info("   ← %s first output after %.1fs", self.label, time.perf_counter() - started)
                        first = False
                    if delta.get("content"):
                        yield delta["content"]
                    for fragment in delta.get("tool_calls") or []:
                        slot = partial.setdefault(fragment.get("index", 0), {"id": "", "name": "", "arguments": ""})
                        fn = fragment.get("function") or {}
                        slot["id"] = fragment.get("id") or slot["id"]
                        slot["name"] += fn.get("name") or ""
                        slot["arguments"] += fn.get("arguments") or ""

        for index, slot in sorted(partial.items()):
            try:
                arguments = json.loads(slot["arguments"] or "{}")
            except json.JSONDecodeError:
                logger.warning("   tool %s sent invalid JSON arguments: %s", slot["name"], slot["arguments"])
                arguments = {}
            logger.info("   ← %s wants tool %s(%s)", self.label, slot["name"], json.dumps(arguments))
            yield ToolCall(id=slot["id"] or f"call_{index}", name=slot["name"], arguments=arguments)

    def assistant_message(self, content: str, calls: List[ToolCall]) -> Message:
        return {
            "role": "assistant",
            "content": content,
            "tool_calls": [
                {
                    "id": c.id,
                    "type": "function",
                    "function": {"name": c.name, "arguments": json.dumps(c.arguments)},
                }
                for c in calls
            ],
        }

    def tool_message(self, call: ToolCall, result: str) -> Message:
        return {"role": "tool", "tool_call_id": call.id, "content": result}

    async def is_up(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                response = await client.get(f"{self.base_url}/models", headers=self._headers())
                return response.status_code == 200
        except httpx.HTTPError as exc:
            logger.warning("   %s unreachable (%s)", self.label, exc)
            return False
