# MCP Servers

Each MCP server lives in its own folder here, with its own `requirements.txt`
and `.venv`, and runs as an independent HTTP service (MCP "streamable HTTP"
transport, path `/mcp`) on its own port.

| Server        | Folder                       | Port | Tools               |
|---------------|------------------------------|------|---------------------|
| Bitcoin Price | `mcp_servers/bitcoin_price/` | 8101 | `get_bitcoin_price` |
| _(next)_      | `mcp_servers/<name>/`        | 8102 |                     |

The backend connects to these servers as an MCP client; the frontend never
talks to them directly.

## Adding a server

1. Copy `bitcoin_price/` to a new folder and change the tools and port.
2. Add its URL to `MCP_SERVERS` in `backend/.env` (comma-separated), e.g.
   `MCP_SERVERS=http://localhost:8101/mcp,http://localhost:8102/mcp`.
3. Restart the backend so it reads the new `.env`.
