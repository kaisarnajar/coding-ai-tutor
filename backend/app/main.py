from typing import AsyncIterator, List, Literal

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .config import settings
from .ollama_client import is_ollama_up, stream_chat

app = FastAPI(title="Coding AI Tutor - Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_methods=["*"],
    allow_headers=["*"],
)


class Message(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    messages: List[Message]


@app.get("/api/health")
async def health() -> dict:
    return {
        "backend": "ok",
        "ollama": "ok" if await is_ollama_up() else "unreachable",
        "model": settings.ollama_model,
    }


@app.post("/api/chat")
async def chat(request: ChatRequest) -> StreamingResponse:
    messages = [m.model_dump() for m in request.messages]

    async def generate() -> AsyncIterator[str]:
        try:
            async for text in stream_chat(messages):
                yield text
        except Exception as exc:  # surface the problem in the chat instead of a silent cut-off
            yield f"\n\n[Error talking to Ollama: {exc}]"

    return StreamingResponse(generate(), media_type="text/plain; charset=utf-8")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=settings.backend_port, reload=True)
