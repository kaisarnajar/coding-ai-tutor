import json
import time
from typing import AsyncIterator, Dict, List

import httpx

from .config import settings
from .log import logger


async def is_ollama_up() -> bool:
    """Return True if the Ollama server answers."""
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            response = await client.get(f"{settings.ollama_url}/api/tags")
            return response.status_code == 200
    except httpx.HTTPError as exc:
        logger.warning("   Ollama unreachable at %s (%s)", settings.ollama_url, exc)
        return False


async def stream_chat(messages: List[Dict[str, str]]) -> AsyncIterator[str]:
    """Send messages to Ollama's /api/chat and yield the reply text piece by piece."""
    payload = {"model": settings.ollama_model, "messages": messages, "stream": True}
    logger.info(
        "   → Ollama POST /api/chat model=%s messages=%d",
        settings.ollama_model,
        len(messages),
    )
    started = time.perf_counter()

    async with httpx.AsyncClient(timeout=None) as client:
        async with client.stream(
            "POST", f"{settings.ollama_url}/api/chat", json=payload
        ) as response:
            if response.status_code != 200:
                body = (await response.aread()).decode(errors="replace")
                raise RuntimeError(f"Ollama returned {response.status_code}: {body}")

            first_token = True
            # Ollama streams one JSON object per line.
            async for line in response.aiter_lines():
                if not line:
                    continue
                chunk = json.loads(line)
                if "error" in chunk:
                    raise RuntimeError(chunk["error"])
                text = chunk.get("message", {}).get("content", "")
                if text:
                    if first_token:
                        logger.info(
                            "   ← Ollama first token after %.1fs",
                            time.perf_counter() - started,
                        )
                        first_token = False
                    yield text
                if chunk.get("done"):
                    break
