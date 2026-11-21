# MCP Servers

Each MCP server lives in its own folder here and runs as an independent HTTP
service (MCP "streamable HTTP" transport) on its own port.

Convention:

| Server        | Folder                 | Port |
|---------------|------------------------|------|
| _(first one)_ | `mcp_servers/<name>/`  | 8101 |
| _(next)_      | `mcp_servers/<name>/`  | 8102 |

The backend connects to these servers as an MCP client; the frontend never
talks to them directly. (Added in step 2.)
