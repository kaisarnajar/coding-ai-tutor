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
.venv/bin/python -m uvicorn app.main:app --reload --port 8000
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

`frontend/.env`: `VITE_BACKEND_URL=http://localhost:8000`
