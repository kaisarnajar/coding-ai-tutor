"""Talks to the MCP servers listed in MCP_SERVERS.

The backend connects to each server for every chat request, so MCP servers can be
started, stopped or restarted at any time without restarting the backend.
"""

import json
from typing import Any, Dict, List, Tuple

from mcp import Client

from .config import settings
from .log import block, logger

# Ollama tool definitions, and which server URL owns each tool name.
OllamaTools = List[Dict[str, Any]]
ToolOwners = Dict[str, str]


def _reason(exc: BaseException) -> str:
    """The real error inside the SDK's exception groups, e.g. 'ConnectError: ...'."""
    while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        exc = exc.exceptions[0]
    return f"{type(exc).__name__}: {exc}"


async def load_tools() -> Tuple[OllamaTools, ToolOwners]:
    """Collect the tools from every MCP server, in the format Ollama expects."""
    tools: OllamaTools = []
    owners: ToolOwners = {}
    for url in settings.mcp_server_urls:
        try:
            async with Client(url) as client:
                listed = (await client.list_tools()).tools
        except Exception as exc:
            logger.warning("   MCP %s unreachable, skipping its tools (%s)", url, _reason(exc))
            continue
        for tool in listed:
            owners[tool.name] = url
            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description or "",
                        "parameters": tool.input_schema,
                    },
                }
            )
    if tools:
        logger.info("   MCP tools available: %s", ", ".join(owners))
    return tools, owners


async def call_tool(owners: ToolOwners, name: str, arguments: Dict[str, Any]) -> str:
    """Run one tool on the MCP server that owns it and return its result as text."""
    url = owners.get(name)
    if url is None:
        result = f"Error: unknown tool {name!r}"
        logger.warning("   tool %s not found", name)
        return result

    logger.info("   → MCP tool %s(%s) on %s", name, json.dumps(arguments), url)
    try:
        async with Client(url) as client:
            response = await client.call_tool(name, arguments)
    except Exception as exc:
        logger.error("   ← MCP tool %s failed: %s", name, _reason(exc))
        return f"Error: tool {name!r} failed: {_reason(exc)}"

    if response.structured_content is not None:
        result = json.dumps(response.structured_content)
    else:
        result = "\n".join(b.text for b in response.content if b.type == "text")
    if response.is_error:
        result = f"Error: {result}"
    logger.info("   ← MCP tool %s result:%s", name, block(result))
    return result


async def server_status() -> Dict[str, str]:
    """Return 'ok (N tools)' or 'unreachable' for each MCP server."""
    status: Dict[str, str] = {}
    for url in settings.mcp_server_urls:
        try:
            async with Client(url) as client:
                count = len((await client.list_tools()).tools)
            status[url] = f"ok ({count} tools)"
        except Exception:
            status[url] = "unreachable"
    return status
