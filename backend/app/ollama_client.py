import json
import time
from typing import Any, AsyncIterator, Dict, List

import httpx

from . import mcp_client
from .config import settings
from .log import logger

# How many rounds of tool calls the model may make for one question.
MAX_TOOL_ROUNDS = 3


async def is_ollama_up() -> bool:
    """Return True if the Ollama server answers."""
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            response = await client.get(f"{settings.ollama_url}/api/tags")
            return response.status_code == 200
    except httpx.HTTPError as exc:
        logger.warning("   Ollama unreachable at %s (%s)", settings.ollama_url, exc)
        return False


async def stream_chat(messages: List[Dict[str, Any]]) -> AsyncIterator[str]:
    """Answer the conversation, calling MCP tools when the model asks for them.

    Reply text is yielded piece by piece as Ollama streams it. If the model asks
    for tools instead, they are run on the MCP servers, their results are added to
    the conversation, and Ollama is asked again.
    """
    messages = list(messages)
    tools, owners = await mcp_client.load_tools()

    for round_no in range(MAX_TOOL_ROUNDS + 1):
        # On the last round no tools are offered, so the model has to answer.
        offer_tools = bool(tools) and round_no < MAX_TOOL_ROUNDS
        content = ""
        tool_calls: List[Dict[str, Any]] = []

        async for chunk in _stream_ollama(messages, tools if offer_tools else None):
            message = chunk.get("message", {})
            tool_calls.extend(message.get("tool_calls") or [])
            text = message.get("content", "")
            if text:
                content += text
                yield text

        if not tool_calls:
            return

        messages.append({"role": "assistant", "content": content, "tool_calls": tool_calls})
        for call in tool_calls:
            name = call["function"]["name"]
            arguments = call["function"].get("arguments") or {}
            result = await mcp_client.call_tool(owners, name, arguments)
            messages.append({"role": "tool", "tool_name": name, "content": result})


async def _stream_ollama(
    messages: List[Dict[str, Any]], tools: List[Dict[str, Any]] | None
) -> AsyncIterator[Dict[str, Any]]:
    """Send one request to Ollama's /api/chat and yield each streamed JSON chunk."""
    payload: Dict[str, Any] = {
        "model": settings.ollama_model,
        "messages": messages,
        "stream": True,
    }
    if tools:
        payload["tools"] = tools
    logger.info(
        "   → Ollama POST /api/chat model=%s messages=%d tools=%d",
        settings.ollama_model,
        len(messages),
        len(tools or []),
    )
    started = time.perf_counter()

    async with httpx.AsyncClient(timeout=None) as client:
        async with client.stream(
            "POST", f"{settings.ollama_url}/api/chat", json=payload
        ) as response:
            if response.status_code != 200:
                body = (await response.aread()).decode(errors="replace")
                raise RuntimeError(f"Ollama returned {response.status_code}: {body}")

            first = True
            # Ollama streams one JSON object per line.
            async for line in response.aiter_lines():
                if not line:
                    continue
                chunk = json.loads(line)
                if "error" in chunk:
                    raise RuntimeError(chunk["error"])
                message = chunk.get("message", {})
                if first and (message.get("content") or message.get("tool_calls")):
                    logger.info(
                        "   ← Ollama first output after %.1fs",
                        time.perf_counter() - started,
                    )
                    first = False
                for call in message.get("tool_calls") or []:
                    fn = call.get("function", {})
                    logger.info(
                        "   ← Ollama wants tool %s(%s)",
                        fn.get("name"),
                        json.dumps(fn.get("arguments")),
                    )
                yield chunk
                if chunk.get("done"):
                    break
