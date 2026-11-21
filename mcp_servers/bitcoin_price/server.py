"""Bitcoin Price MCP server.

Runs on its own port (default 8101) using MCP's Streamable HTTP transport at /mcp.
Prices come from CoinGecko's free public API (no API key needed).
"""

import logging
import os
import sys
from datetime import datetime, timezone

import httpx
from mcp.server import MCPServer

COINGECKO_URL = "https://api.coingecko.com/api/v3/simple/price"
PORT = int(os.getenv("PORT", "8101"))

logger = logging.getLogger("bitcoin_price")
_handler = logging.StreamHandler(sys.stdout)
_handler.setFormatter(
    logging.Formatter("%(asctime)s [bitcoin_price] %(message)s", datefmt="%H:%M:%S")
)
logger.addHandler(_handler)
logger.setLevel(logging.INFO)
logger.propagate = False
# Hide uvicorn's per-request "POST /mcp" lines and httpx's request lines; the tool log
# above is more useful. (A filter, because uvicorn resets `disabled` when it starts.)
logging.getLogger("uvicorn.access").addFilter(lambda record: False)
logging.getLogger("httpx").setLevel(logging.WARNING)

mcp = MCPServer(
    "bitcoin_price",
    instructions="Live Bitcoin (BTC) price lookups.",
)


@mcp.tool()
async def get_bitcoin_price(currency: str = "usd") -> dict:
    """Get the current live price of Bitcoin (BTC).

    Use this whenever the user asks about the Bitcoin/BTC price or value.

    Args:
        currency: Currency code for the price, e.g. "usd", "eur", "inr". Defaults to "usd".
    """
    currency = currency.strip().lower() or "usd"
    logger.info("→ get_bitcoin_price(currency=%r)", currency)

    params = {
        "ids": "bitcoin",
        "vs_currencies": currency,
        "include_24hr_change": "true",
        "include_last_updated_at": "true",
    }
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(COINGECKO_URL, params=params)
        response.raise_for_status()
        data = response.json().get("bitcoin", {})

    if currency not in data:
        result = {"error": f"Unsupported currency: {currency!r}. Try a code like 'usd', 'eur' or 'inr'."}
        logger.info("← %s", result)
        return result

    updated = data.get("last_updated_at")
    result = {
        "coin": "bitcoin",
        "currency": currency.upper(),
        "price": data[currency],
        # Ready-made text so small models don't have to format big numbers themselves.
        "price_formatted": f"{data[currency]:,} {currency.upper()}",
        "change_24h_percent": round(data.get(f"{currency}_24h_change", 0.0), 2),
        "last_updated_utc": (
            datetime.fromtimestamp(updated, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            if updated
            else None
        ),
    }
    logger.info("← %s", result)
    return result


if __name__ == "__main__":
    logger.info("Bitcoin Price MCP server on http://localhost:%d/mcp", PORT)
    mcp.run(transport="streamable-http", host="127.0.0.1", port=PORT)
