"""PDF Q&A MCP server.

Runs on its own port (default 8103) using MCP's Streamable HTTP transport at /mcp.

Two tools:
- ingest_pdf: read a PDF the learner uploaded, split it into chunks, embed them and
  save them in the Qdrant vector database.
- query_pdf: find the chunks most relevant to a question.

How a PDF gets here: the frontend uploads it to the backend, which saves it as
<UPLOAD_DIR>/<file_id>.pdf (plus <file_id>.json with its original name) and tells
the model the file_id. The model then calls ingest_pdf(file_id). This server only
reads PDFs from UPLOAD_DIR.

Embeddings come from Ollama (default model nomic-embed-text), even when the chat
model is served by an API. Chunks and their embeddings are stored in Qdrant
(see store.py and vector_db/docker-compose.yml), so they survive restarts.
"""

import asyncio
import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from typing import List, Optional, Tuple

import httpx
from mcp.server import MCPServer

from chunking import read_pages, split_pages
from store import Document, QdrantStore

PORT = int(os.getenv("PORT", "8103"))
UPLOAD_DIR = Path(
    os.getenv("UPLOAD_DIR") or Path(__file__).resolve().parents[2] / "data" / "uploads"
).resolve()
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "pdf_chunks")
CHUNK_SIZE = 1000  # characters per chunk
CHUNK_OVERLAP = 150  # characters shared by neighbouring chunks
EMBED_BATCH = 32  # chunks embedded per Ollama request
MAX_TOP_K = 8

logger = logging.getLogger("pdf_qa")
_handler = logging.StreamHandler(sys.stdout)
_handler.setFormatter(logging.Formatter("%(asctime)s [pdf_qa] %(message)s", datefmt="%H:%M:%S"))
logger.addHandler(_handler)
logger.setLevel(logging.INFO)
logger.propagate = False
# Hide uvicorn's per-request "POST /mcp" lines and httpx's request lines.
logging.getLogger("uvicorn.access").addFilter(lambda record: False)
logging.getLogger("httpx").setLevel(logging.WARNING)

mcp = MCPServer("pdf_qa", instructions="Save PDFs the learner uploads and answer questions from them.")
store = QdrantStore(QDRANT_URL, QDRANT_COLLECTION)


def _block(text: str) -> str:
    """Full text on its own indented lines, for the log."""
    return "".join(f"\n      {line}" for line in text.splitlines() or [""])


def _find_upload(file_id: str) -> Optional[Tuple[str, Path, str]]:
    """Return (id, pdf path, original name) for an uploaded file, or None.

    Small models sometimes wrap the id ("file_id=ab12cd34") or pass the file name
    instead, so both are accepted. Only files inside UPLOAD_DIR are ever opened.
    """
    wanted = file_id.strip().lower()
    match = re.search(r"\b[0-9a-f]{8}\b", wanted)
    candidates = [match.group(0)] if match else []
    for meta_file in UPLOAD_DIR.glob("*.json"):
        try:
            name = json.loads(meta_file.read_text(encoding="utf-8")).get("name", "")
        except (OSError, ValueError):
            continue
        if name.lower() == wanted:
            candidates.append(meta_file.stem)
    for key in candidates:
        pdf = UPLOAD_DIR / f"{key}.pdf"
        if pdf.is_file():
            meta = UPLOAD_DIR / f"{key}.json"
            name = json.loads(meta.read_text(encoding="utf-8")).get("name", pdf.name) if meta.is_file() else pdf.name
            return key, pdf, name
    return None


async def _embed(texts: List[str]) -> List[List[float]]:
    """Embed texts with Ollama, a batch at a time."""
    vectors: List[List[float]] = []
    async with httpx.AsyncClient(timeout=120) as client:
        for i in range(0, len(texts), EMBED_BATCH):
            response = await client.post(
                f"{OLLAMA_URL}/api/embed",
                json={"model": EMBED_MODEL, "input": texts[i : i + EMBED_BATCH]},
            )
            if response.status_code != 200:
                raise RuntimeError(f"Ollama embed returned {response.status_code}: {response.text}")
            vectors.extend(response.json()["embeddings"])
    return vectors


@mcp.tool()
async def ingest_pdf(file_id: str) -> dict:
    """Save (ingest) a PDF the learner attached, so questions can be answered from it.

    Call this when a message contains "[Attached PDF: ..., file_id=...]" and the
    learner wants the PDF saved, read or used. Pass the file_id from that line.
    Calling it again for the same file is harmless.

    Args:
        file_id: The file_id shown in the "[Attached PDF: ...]" line, e.g. "3f9a1c2e".
    """
    logger.info("→ ingest_pdf(file_id=%r)", file_id)
    found = _find_upload(file_id)
    if found is None:
        result = {"error": f"No uploaded PDF with file_id {file_id!r}. Ask the learner to attach it again."}
        logger.info("← %s", result)
        return result
    doc_id, path, name = found

    try:
        doc = await store.get(doc_id)
    except Exception as exc:
        result = {"error": f"The vector database is not reachable ({type(exc).__name__}). Is Qdrant running?"}
        logger.info("← %s", result)
        return result
    if doc is not None:
        result = {"status": "already saved", "file_id": doc_id, "name": name, "pages": doc.pages, "chunks": doc.chunks}
        logger.info("← %s", result)
        return result

    started = time.perf_counter()
    try:
        pages = await asyncio.to_thread(read_pages, path)
    except Exception as exc:
        result = {"error": f"Could not read {name}: {exc}"}
        logger.info("← %s", result)
        return result
    chunks = split_pages(pages, CHUNK_SIZE, CHUNK_OVERLAP)
    if not chunks:
        result = {"error": f"No text found in {name}. It may be a scanned PDF (images only), which is not supported."}
        logger.info("← %s", result)
        return result

    # nomic-embed-text expects these task prefixes on documents and questions.
    vectors = await _embed([f"search_document: {c.text}" for c in chunks])
    doc = Document(doc_id=doc_id, name=name, pages=len(pages), chunks=len(chunks))
    await store.add(doc, [(c.page, c.text, v) for c, v in zip(chunks, vectors)])

    result = {
        "status": "saved",
        "file_id": doc_id,
        "name": name,
        "pages": len(pages),
        "pages_with_text": sum(1 for p in pages if p),
        "chunks": len(chunks),
    }
    logger.info("← %s in %.1fs", result, time.perf_counter() - started)
    return result


@mcp.tool()
async def query_pdf(question: str, top_k: int = 4) -> dict:
    """Find the passages in the saved PDFs that answer a question.

    Searches all saved PDFs at once; no file_id is needed. Call this when the learner asks about the content of a PDF they saved
    ("what does the PDF say about...", "summarise chapter 2", ...). Answer only from
    the returned passages and cite their page numbers.

    Args:
        question: The learner's question, or the topic to look up.
        top_k: How many passages to return (1 to 8). Defaults to 4.
    """
    top_k = max(1, min(int(top_k or 4), MAX_TOP_K))
    logger.info("→ query_pdf(question=%r, top_k=%d)", question, top_k)
    try:
        empty = await store.is_empty()
    except Exception as exc:
        result = {"error": f"The vector database is not reachable ({type(exc).__name__}). Is Qdrant running?"}
        logger.info("← %s", result)
        return result
    if empty:
        result = {"error": "No PDFs have been saved yet. Ask the learner to attach a PDF with the 📎 button."}
        logger.info("← %s", result)
        return result

    [vector] = await _embed([f"search_query: {question}"])
    hits = await store.search(vector, top_k)
    result = {
        "saved_pdfs": [d.name for d in await store.list()],
        "passages": [
            {"pdf": c.name, "page": c.page, "score": round(score, 3), "text": c.text}
            for score, c in hits
        ],
    }
    for score, c in hits:
        logger.info("   %.3f  %s p.%d:%s", score, c.name, c.page, _block(c.text))
    logger.info("← %d passages", len(hits))
    return result


if __name__ == "__main__":
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    logger.info(
        "PDF Q&A MCP server on http://localhost:%d/mcp (uploads: %s, embeddings: %s, vector DB: %s/%s)",
        PORT, UPLOAD_DIR, EMBED_MODEL, QDRANT_URL, QDRANT_COLLECTION,
    )
    mcp.run(transport="streamable-http", host="127.0.0.1", port=PORT)
