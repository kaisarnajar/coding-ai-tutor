# MCP Servers

Each MCP server lives in its own folder here, with its own `requirements.txt`
and `.venv`, and runs as an independent HTTP service (MCP "streamable HTTP"
transport, path `/mcp`) on its own port.

| Server        | Folder                       | Port | Tools               |
|---------------|------------------------------|------|---------------------|
| Bitcoin Price | `mcp_servers/bitcoin_price/` | 8101 | `get_bitcoin_price` |
| Code Runner   | `mcp_servers/code_runner/`   | 8102 | `run_python`        |
| PDF Q&A       | `mcp_servers/pdf_qa/`        | 8103 | `ingest_pdf`, `query_pdf`, `read_pdf_pages` (stores chunks in Qdrant, see `vector_db/`) |
| _(next)_      | `mcp_servers/<name>/`        | 8104 |                     |

The backend connects to these servers as an MCP client; the frontend never
talks to them directly.

## Adding a server

1. Copy `bitcoin_price/` to a new folder and change the tools and port.
2. Add its URL to `MCP_SERVERS` in `backend/.env` (comma-separated), e.g.
   `MCP_SERVERS=http://localhost:8101/mcp,http://localhost:8102/mcp,http://localhost:8103/mcp,http://localhost:8104/mcp`.
3. The backend re-reads `.env` on every question, so no restart is needed.
