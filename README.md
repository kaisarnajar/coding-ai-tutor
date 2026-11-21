# Coding AI Tutor

A local coding tutor: a React frontend talks to a FastAPI backend, which talks
to a local Ollama model. When the model needs live data it calls tools on MCP
servers, each running on its own port.

```
Browser ──► Frontend (:5173) ──► Backend (:8000) ──► Ollama (:11434)
                                     └──► MCP servers (:8101, :8102, …)
```

| MCP server      | Folder                      | Port | Tools               |
|-----------------|-----------------------------|------|---------------------|
| Bitcoin Price   | `mcp_servers/bitcoin_price` | 8101 | `get_bitcoin_price` |
| Code Runner     | `mcp_servers/code_runner`   | 8102 | `run_python`        |

| Folder         | What it is                           | Port  |
|----------------|--------------------------------------|-------|
| `frontend/`    | Vite + React + TypeScript chat UI    | 5173  |
| `backend/`     | FastAPI; the only part that calls Ollama / MCP | 8000  |
| `mcp_servers/` | One folder per MCP server            | 8101+ |

## Prerequisites

- [Ollama](https://ollama.com) running, with the model pulled: `ollama pull qwen2.5:3b`
- [uv](https://docs.astral.sh/uv/) and Python 3.12 (`uv python install 3.12`); the MCP SDK needs Python 3.10+
- Node 18+

## Run it

**1. Ollama** (skip if the Ollama app is already running)

```bash
ollama serve
```

**2. Backend** (first time: create the venv and `.env`)

```bash
cd backend
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt
cp .env.example .env
.venv/bin/python -m uvicorn app.main:app --reload --port 8000 --no-access-log
```

**3. MCP servers** (one terminal each; first time: create the venv)

```bash
cd mcp_servers/bitcoin_price
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt
.venv/bin/python server.py
```

```bash
cd mcp_servers/code_runner
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt
.venv/bin/python server.py
```

The Code Runner runs untrusted code, so it is locked down: a separate process
in a temporary folder, a 10 s time limit and a 5 s CPU limit, and on macOS a
`sandbox-exec` sandbox with no network, no access to your home folder, no
writes outside the temp folder and no starting other programs. Without
`sandbox-exec` (e.g. on Linux) it refuses to run code.

Check it: <http://localhost:8000/api/health> should show `"ollama": "ok"` and
`"ok (1 tools)"` for each MCP server. MCP servers can be started or
restarted at any time; the backend reconnects on every question.

**4. Frontend** (in another terminal)

```bash
cd frontend
npm install
cp .env.example .env
npm run dev
```

Open <http://localhost:5173>.

## System prompt

The tutor's instructions live in
[`backend/app/prompts/system.md`](backend/app/prompts/system.md). The backend
reads it on every question and sends it to the model as the first (`system`)
message, so edits take effect on the next question with no restart. The
frontend never sends or sees it, and any `system` message from the browser is
dropped. The backend log shows `system prompt: system.md (N chars)` per question.

## Debug logs

The page calls `/api/...` on the Vite dev server, which forwards it to the
backend. Both terminals print a short line for every call:

```
# frontend terminal
09:41:02 [frontend] → POST /api/chat messages=1 question:
      What is a Python list?
09:41:05 [frontend] ← POST /api/chat 200 (3.1s):
      A Python list is an ordered, mutable collection of items.
      Example: nums = [1, 2, 3]

# backend terminal
09:41:02 [backend] → POST /api/chat
09:41:02 [backend]    question:
      What is a Python list?
09:41:02 [backend]    → Ollama POST /api/chat model=qwen2.5:3b messages=1
09:41:02 [backend] ← POST /api/chat 200 (4 ms)
09:41:03 [backend]    ← Ollama first token after 0.6s
09:41:05 [backend]    reply done: 84 chars in 3.1s:
      A Python list is an ordered, mutable collection of items.
      Example: nums = [1, 2, 3]
```

The full question and reply are printed, with their line breaks kept.

When the model uses a tool, the backend terminal also shows the tool call and
its full result, and the MCP server's terminal logs the call too:

```
# backend terminal
10:20:01 [backend]    MCP tools available: get_bitcoin_price
10:20:01 [backend]    → Ollama POST /api/chat model=qwen2.5:3b messages=1 tools=1
10:20:02 [backend]    ← Ollama wants tool get_bitcoin_price({"currency": "usd"})
10:20:02 [backend]    → MCP tool get_bitcoin_price({"currency": "usd"}) on http://localhost:8101/mcp
10:20:02 [backend]    ← MCP tool get_bitcoin_price result:
      {"coin": "bitcoin", "currency": "USD", "price": 56284, ...}
10:20:02 [backend]    → Ollama POST /api/chat model=qwen2.5:3b messages=3 tools=1

# bitcoin_price terminal
10:20:02 [bitcoin_price] → get_bitcoin_price(currency='usd')
10:20:02 [bitcoin_price] ← {'coin': 'bitcoin', 'currency': 'USD', 'price': 56284, ...}
```

The `← … 200` line comes right away because the reply is streamed; the
`reply done` line marks the end. Errors (backend or Ollama down) are logged too.

## Backend API

| Method | Path          | Body / response |
|--------|---------------|-----------------|
| GET    | `/api/health` | `{"backend": "ok", "ollama": "ok" \| "unreachable", "model": "..."}` |
| POST   | `/api/chat`   | Body `{"messages": [{"role": "user", "content": "..."}]}`; streams the reply as plain text |

## Settings

`backend/.env` (see `.env.example`):

| Variable          | Default                  |
|-------------------|--------------------------|
| `OLLAMA_URL`      | `http://localhost:11434` |
| `OLLAMA_MODEL`    | `qwen2.5:3b`             |
| `BACKEND_PORT`    | `8000`                   |
| `FRONTEND_ORIGIN` | `http://localhost:5173`  |
| `MCP_SERVERS`     | `http://localhost:8101/mcp,http://localhost:8102/mcp` (comma-separated) |

`frontend/.env`: `BACKEND_URL=http://localhost:8000` (where the Vite dev server forwards `/api`)
