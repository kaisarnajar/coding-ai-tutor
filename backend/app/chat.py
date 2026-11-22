"""Answers a conversation with the configured model, running MCP tools when it asks."""

from pathlib import Path
from typing import Any, AsyncIterator, Dict, List

from . import mcp_client
from .config import get_settings
from .llm import ToolCall, get_provider
from .log import logger

# How many rounds of tool calls the model may make for one question.
MAX_TOOL_ROUNDS = 5

# The tutor's instructions. Read on every question, so edits apply without a restart.
SYSTEM_PROMPT_FILE = Path(__file__).parent / "prompts" / "system.md"


def load_system_prompt() -> str:
    """Return the system prompt text, or "" if the file is missing."""
    try:
        return SYSTEM_PROMPT_FILE.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        logger.warning("   system prompt file not found: %s", SYSTEM_PROMPT_FILE)
        return ""


async def stream_chat(messages: List[Dict[str, Any]]) -> AsyncIterator[str]:
    """Answer the conversation, calling MCP tools when the model asks for them.

    Reply text is yielded piece by piece as the model streams it. If the model asks
    for tools instead, they are run on the MCP servers, their results are added to
    the conversation, and the model is asked again.
    """
    settings = get_settings()  # re-read, so a model change in backend/.env applies now
    provider = get_provider(settings)
    logger.info("   model: %s via %s", provider.model, provider.label)

    # The frontend only sends user/assistant messages; the tutor's instructions go first.
    messages = [m for m in messages if m.get("role") != "system"]
    system_prompt = load_system_prompt()
    if system_prompt:
        messages.insert(0, {"role": "system", "content": system_prompt})
        logger.info("   system prompt: %s (%d chars)", SYSTEM_PROMPT_FILE.name, len(system_prompt))
    tools, owners = await mcp_client.load_tools(settings)

    for round_no in range(MAX_TOOL_ROUNDS + 1):
        # On the last round no tools are offered, so the model has to answer.
        offer_tools = bool(tools) and round_no < MAX_TOOL_ROUNDS
        content = ""
        calls: List[ToolCall] = []

        async for piece in provider.stream(messages, tools if offer_tools else None):
            if isinstance(piece, ToolCall):
                calls.append(piece)
            else:
                content += piece
                yield piece

        # Done if the model just answered. On the last round tools were not offered,
        # so any tool request is ignored (otherwise the reply would end with no answer).
        if not calls or not offer_tools:
            return

        messages.append(provider.assistant_message(content, calls))
        for call in calls:
            # Small models often send null for optional arguments; leave those out
            # so the tool's own defaults apply.
            arguments = {k: v for k, v in call.arguments.items() if v is not None}
            result = await mcp_client.call_tool(owners, call.name, arguments)
            messages.append(provider.tool_message(call, result))
