import time
from typing import AsyncIterator, List, Literal

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .config import settings
from .log import logger, preview
from .ollama_client import is_ollama_up, stream_chat

app = FastAPI(title="Coding AI Tutor - Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log every incoming request and its status code."""
    started = time.perf_counter()
    logger.info("→ %s %s", request.method, request.url.path)
    response = await call_next(request)
    logger.info(
        "← %s %s %d (%.0f ms)",
        request.method,
        request.url.path,
        response.status_code,
        (time.perf_counter() - started) * 1000,
    )
    return response


class Message(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    messages: List[Message]


@app.get("/api/health")
async def health() -> dict:
    result = {
        "backend": "ok",
        "ollama": "ok" if await is_ollama_up() else "unreachable",
        "model": settings.ollama_model,
    }
    logger.info("   health: %s", result)
    return result


@app.post("/api/chat")
async def chat(request: ChatRequest) -> StreamingResponse:
    messages = [m.model_dump() for m in request.messages]
    logger.info("   question: %r", preview(messages[-1]["content"]) if messages else "")

    async def generate() -> AsyncIterator[str]:
        started = time.perf_counter()
        reply = ""
        try:
            async for text in stream_chat(messages):
                reply += text
                yield text
            logger.info(
                "   reply done: %d chars in %.1fs: %r",
                len(reply),
                time.perf_counter() - started,
                preview(reply),
            )
        except Exception as exc:  # surface the problem in the chat instead of a silent cut-off
            logger.error("   chat failed after %.1fs: %s", time.perf_counter() - started, exc)
            yield f"\n\n[Error talking to Ollama: {exc}]"

    return StreamingResponse(generate(), media_type="text/plain; charset=utf-8")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=settings.backend_port,
        reload=True,
        access_log=False,  # our own request log above replaces uvicorn's
    )
