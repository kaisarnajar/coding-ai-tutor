import json
from typing import AsyncIterator, Dict, List

import httpx

from .config import settings


async def is_ollama_up() -> bool:
    """Return True if the Ollama server answers."""
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            response = await client.get(f"{settings.ollama_url}/api/tags")
            return response.status_code == 200
    except httpx.HTTPError:
        return False


async def stream_chat(messages: List[Dict[str, str]]) -> AsyncIterator[str]:
    """Send messages to Ollama's /api/chat and yield the reply text piece by piece."""
    payload = {"model": settings.ollama_model, "messages": messages, "stream": True}

    async with httpx.AsyncClient(timeout=None) as client:
        async with client.stream(
            "POST", f"{settings.ollama_url}/api/chat", json=payload
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
                text = chunk.get("message", {}).get("content", "")
                if text:
                    yield text
                if chunk.get("done"):
                    break
