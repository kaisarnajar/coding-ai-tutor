# Coding AI Tutor

A coding tutor: a React frontend talks to a FastAPI backend, which talks to a
chat model, either a local Ollama model or a model behind an API such as
OpenRouter (see [Choosing the model](#choosing-the-model)). When the model needs
a tool it calls one of the MCP servers, each running on its own port.

```
Browser ──► Frontend (:5173) ──► Backend (:8000) ──► Ollama (:11434)  or  an OpenAI-compatible API
                                     └──► MCP servers (:8101, :8102, …)
```

| MCP server      | Folder                      | Port | Tools               |
|-----------------|-----------------------------|------|---------------------|
| Bitcoin Price   | `mcp_servers/bitcoin_price` | 8101 | `get_bitcoin_price` |
| Code Runner     | `mcp_servers/code_runner`   | 8102 | `run_python`        |
| PDF Q&A         | `mcp_servers/pdf_qa`        | 8103 | `ingest_pdf`, `query_pdf` |

| Folder         | What it is                           | Port  |
|----------------|--------------------------------------|-------|
| `frontend/`    | Vite + React + TypeScript chat UI    | 5173  |
| `backend/`     | FastAPI; the only part that calls the model / MCP | 8000  |
| `mcp_servers/` | One folder per MCP server            | 8101+ |

## Prerequisites

- For a local model: [Ollama](https://ollama.com) running, with the model pulled: `ollama pull qwen2.5:3b`
  (for an API model, an API key instead; see [Choosing the model](#choosing-the-model))
- [uv](https://docs.astral.sh/uv/) and Python 3.12 (`uv python install 3.12`); the MCP SDK needs Python 3.10+
- Node 18+

## Run it

**1. Ollama** (skip if the Ollama app is already running, or if you use an API model)

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

```bash
cd mcp_servers/pdf_qa
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt
.venv/bin/python server.py
```

The PDF Q&A server needs Ollama's embedding model: `ollama pull nomic-embed-text`.

The Code Runner runs untrusted code, so it is locked down: a separate process
in a temporary folder, a 10 s time limit and a 5 s CPU limit, and on macOS a
`sandbox-exec` sandbox with no network, no access to your home folder, no
writes outside the temp folder and no starting other programs. Without
`sandbox-exec` (e.g. on Linux) it refuses to run code.

Check it: <http://localhost:8000/api/health> should show `"llm": "Ollama: ok"` and
`"ok (N tools)"` for each MCP server. MCP servers can be started or
restarted at any time; the backend reconnects on every question.

**4. Frontend** (in another terminal)

```bash
cd frontend
npm install
cp .env.example .env
npm run dev
```

Open <http://localhost:5173>.

## Choosing the model

Two settings in `backend/.env` pick the model. They are read again on every
question, so a change applies to the next question with no restart.

**Local model with Ollama** (default)

```
LLM_PROVIDER=ollama
LLM_MODEL=qwen2.5:3b
```

Any model from `ollama list` works, including Ollama cloud models such as
`glm-5.3:cloud`. Pull it first, e.g. `ollama pull mimo-v2.6`.

**Model through an API**

`LLM_PROVIDER=openai` works with any OpenAI-compatible API. For OpenRouter:

```
LLM_PROVIDER=openai
LLM_MODEL=anthropic/claude-sonnet-5.5
API_BASE_URL=https://openrouter.ai/api/v1
API_KEY=<your OpenRouter key>
```

Other services only need a different `API_BASE_URL`, `LLM_MODEL` and key,
e.g. OpenAI (`https://api.openai.com/v1`), or LM Studio on your own machine
(`http://localhost:1234/v1`, no key). Keep `API_KEY` only in `backend/.env`,
which git ignores. Pick a model that supports tool calling, or the MCP tools
won't be used.

The code for each provider is in [`backend/app/llm/`](backend/app/llm/): one
file per provider, all with the same small interface (`base.py`), so adding
another kind of provider means adding one file there.

## PDFs

Click 📎 next to the input to attach a PDF (up to 20 MB). It is uploaded to the
backend right away and saved in `data/uploads/` (ignored by git); the model
only gets a short `file_id` with your next message:

```
Save this PDF.
[Attached PDF: notes.pdf, file_id=3f9a1c2e]
```

The model then picks the tool from what you ask:

| You say | Tool the model calls |
|---------|----------------------|
| Attach a PDF ("Save this PDF", or just send it) | `ingest_pdf(file_id)`: reads the text page by page, splits it into ~1000-character chunks (150 overlap), embeds them with `nomic-embed-text` and keeps them in memory |
| "What does my PDF say about loops?" | `query_pdf(question)`: returns the 4 most similar chunks with page numbers; the answer cites them |
| A general coding question | no PDF tool |

Stage 1 keeps the chunks in the PDF Q&A server's memory, so they are lost when
that server restarts (attach the PDF again). Only
[`mcp_servers/pdf_qa/store.py`](mcp_servers/pdf_qa/store.py) needs replacing to
move to a vector database. Scanned PDFs (images only) have no text and are
rejected. Small models sometimes skip the tools; a stronger model helps (see
[Choosing the model](#choosing-the-model)).

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
09:41:02 [backend]    model: qwen2.5:3b via Ollama
09:41:02 [backend]    → Ollama POST /api/chat model=qwen2.5:3b messages=1
09:41:02 [backend] ← POST /api/chat 200 (4 ms)
09:41:03 [backend]    ← Ollama first output after 0.6s
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
`reply done` line marks the end. Errors (backend or model down) are logged too.
With an API model the `Ollama` lines read e.g. `→ API openrouter.ai POST /chat/completions ...`.

## Backend API

| Method | Path          | Body / response |
|--------|---------------|-----------------|
| GET    | `/api/health` | `{"backend": "ok", "provider": "ollama", "model": "...", "llm": "Ollama: ok" \| "...: unreachable", "mcp_servers": {...}}` |
| POST   | `/api/chat`   | Body `{"messages": [{"role": "user", "content": "...", "attachments": [{"file_id": "...", "name": "..."}]}]}` (`attachments` optional); streams the reply as plain text |
| POST   | `/api/uploads` | Multipart form with a `file` (PDF, max 20 MB); returns `{"file_id", "name", "size"}` |

## Settings

`backend/.env` (see `.env.example`):

| Variable          | Default                  |
|-------------------|--------------------------|
| `LLM_PROVIDER`    | `ollama` (or `openai` for any OpenAI-compatible API) |
| `LLM_MODEL`       | `qwen2.5:3b`             |
| `OLLAMA_URL`      | `http://localhost:11434` (used with `ollama`) |
| `API_BASE_URL`    | `https://openrouter.ai/api/v1` (used with `openai`) |
| `API_KEY`         | empty (used with `openai`; secret, never commit it) |
| `BACKEND_PORT`    | `8000`                   |
| `FRONTEND_ORIGIN` | `http://localhost:5173`  |
| `MCP_SERVERS`     | `http://localhost:8101/mcp,http://localhost:8102/mcp,http://localhost:8103/mcp` (comma-separated) |
| `UPLOAD_DIR`      | `<project>/data/uploads` (shared with the PDF Q&A server) |

`frontend/.env`: `BACKEND_URL=http://localhost:8000` (where the Vite dev server forwards `/api`)
