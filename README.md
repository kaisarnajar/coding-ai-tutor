# Coding AI Tutor

A local coding tutor: a React frontend talks to a FastAPI backend, which talks
to a local Ollama model (and, in later steps, to MCP servers).

```
Browser ──► Frontend (:5173) ──► Backend (:8000) ──► Ollama (:11434)
                                     └──► MCP servers (:8101, :8102, …)  [later]
```

| Folder         | What it is                           | Port  |
|----------------|--------------------------------------|-------|
| `frontend/`    | Vite + React + TypeScript chat UI    | 5173  |
| `backend/`     | FastAPI; the only part that calls Ollama / MCP | 8000  |
| `mcp_servers/` | One folder per MCP server (step 2+)  | 8101+ |

## Prerequisites

- [Ollama](https://ollama.com) running, with the model pulled: `ollama pull qwen2.5:3b`
- Python 3.9+
- Node 18+

## Run it

**1. Ollama** (skip if the Ollama app is already running)

```bash
ollama serve
```

**2. Backend** (first time: create the venv and `.env`)

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
.venv/bin/python -m uvicorn app.main:app --reload --port 8000 --no-access-log
```

Check it: <http://localhost:8000/api/health> should show `"ollama": "ok"`.

**3. Frontend** (in a second terminal)

```bash
cd frontend
npm install
cp .env.example .env
npm run dev
```

Open <http://localhost:5173>.

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

`frontend/.env`: `BACKEND_URL=http://localhost:8000` (where the Vite dev server forwards `/api`)
