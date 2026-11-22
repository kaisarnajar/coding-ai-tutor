"""PDF Q&A MCP server.

Runs on its own port (default 8103) using MCP's Streamable HTTP transport at /mcp.

Three tools:
- ingest_pdf: read a PDF the learner uploaded, split it into chunks, embed them and
  save them in the Qdrant vector database.
- query_pdf: find the chunks most relevant to a question (search by topic).
- read_pdf_pages: return the full text of given pages (read a known place, e.g. the
  table of contents), for questions that similarity search cannot answer.

A PDF's id is a hash of its content, so the same file is only ever stored once.

How a PDF gets here: the frontend uploads it to the backend, which saves it as
<UPLOAD_DIR>/<file_id>.pdf (plus <file_id>.json with its original name) and tells
the model the file_id. The model then calls ingest_pdf(file_id). This server only
reads PDFs from UPLOAD_DIR.

Embeddings come from Ollama (default model nomic-embed-text), even when the chat
model is served by an API. Chunks and their embeddings are stored in Qdrant
(see store.py and vector_db/docker-compose.yml), so they survive restarts.
"""

import asyncio
import hashlib
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
MAX_PAGES_PER_READ = 5  # so one call cannot flood the model with a whole book

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


def _content_id(path: Path) -> str:
    """Same bytes -> same id. Matches the file_id the backend gives new uploads."""
    return hashlib.sha256(path.read_bytes()).hexdigest()[:8]


def _parse_pages(pages: str) -> List[int]:
    """'2' -> [2], '10-12' -> [10, 11, 12], '3, 5' -> [3, 5]."""
    numbers: List[int] = []
    for part in str(pages).replace(" ", "").split(","):
        if not part:
            continue
        if "-" in part:
            start, end = (int(x) for x in part.split("-", 1))
            numbers.extend(range(start, end + 1))
        else:
            numbers.append(int(part))
    return sorted(set(numbers))


CONTENTS_WORDS = {"contents", "content", "toc", "table of contents", "index", "chapters"}


async def _contents_pages(doc: Document) -> List[int]:
    """Find the table of contents among the first 10 pages.

    A page counts if it says "contents" or lists several chapters/sections. If none
    is found, pages 1-3 are returned.
    """
    first = list(range(1, min(doc.pages, 10) + 1))
    rows = await store.get_pages(doc.doc_id, first)
    found = []
    for n in first:
        text = _join_chunks([t for page, _, t in rows if page == n])
        entries = len(re.findall(r"(?im)^\s*(chapter|section|part|unit|lesson)?\s*\d+[.:)]?\s+\S", text))
        if "contents" in text.lower() or entries >= 8:
            found.append(n)
    return found[:MAX_PAGES_PER_READ] or first[:3]


def _join_chunks(texts: List[str]) -> str:
    """Join neighbouring chunks of one page, dropping the text they share (the overlap)."""
    joined = ""
    for text in texts:
        overlap = 0
        for size in range(min(len(joined), len(text), CHUNK_OVERLAP + 50), 19, -1):  # 20+ chars, so a chance match is not taken for the overlap
            if joined.endswith(text[:size]):
                overlap = size
                break
        joined += text[overlap:] if overlap else (("\n" if joined else "") + text)
    return joined


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
    _, path, name = found
    doc_id = _content_id(path)

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

    Searches all saved PDFs at once; no file_id is needed. Call this when the learner
    asks what a saved PDF says about a topic ("what does the PDF say about...",
    "explain decorators from my notes"). Answer only from the returned passages and
    cite their page numbers. Not for listing chapters or reading a given page: use
    read_pdf_pages for those.

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
    # Ask for extra results and skip repeated text, so duplicates never crowd out
    # other passages.
    hits, seen = [], set()
    for score, c in await store.search(vector, top_k * 3):
        if c.text not in seen:
            seen.add(c.text)
            hits.append((score, c))
        if len(hits) == top_k:
            break
    result = {
        "saved_pdfs": sorted({d.name for d in await store.list()}),
        "passages": [
            {"pdf": c.name, "page": c.page, "score": round(score, 3), "text": c.text}
            for score, c in hits
        ],
    }
    for score, c in hits:
        logger.info("   %.3f  %s p.%d:%s", score, c.name, c.page, _block(c.text))
    logger.info("← %d passages", len(hits))
    return result


@mcp.tool()
async def read_pdf_pages(pages: str, pdf: str = "") -> dict:
    """Read the full text of specific pages of a saved PDF.

    Use this instead of query_pdf when the learner asks about a place in the PDF
    rather than a topic:
    - "list all the chapters", "what topics does it cover", "what is the first
      chapter": pass pages="contents" to get the table of contents.
    - "what is on page 5", "summarise pages 10-12": pass those page numbers.
    At most 5 pages per call.

    Args:
        pages: "contents" for the table of contents, or page numbers such as "2", "10-12" or "3, 5".
        pdf: The PDF's name, e.g. "notes.pdf". Can be left empty when only one PDF is saved.
    """
    logger.info("→ read_pdf_pages(pages=%r, pdf=%r)", pages, pdf)
    try:
        documents = await store.list()
    except Exception as exc:
        result = {"error": f"The vector database is not reachable ({type(exc).__name__}). Is Qdrant running?"}
        logger.info("← %s", result)
        return result
    if not documents:
        result = {"error": "No PDFs have been saved yet. Ask the learner to attach a PDF with the 📎 button."}
        logger.info("← %s", result)
        return result

    wanted = pdf.strip().lower()
    matches = [d for d in documents if wanted and (d.name.lower() == wanted or d.doc_id == wanted)]
    if not matches and len(documents) == 1:
        matches = documents
    if not matches:
        result = {"error": f"Say which PDF to read. Saved PDFs: {', '.join(d.name for d in documents)}"}
        logger.info("← %s", result)
        return result
    doc = matches[0]

    try:
        if str(pages).strip().lower() in CONTENTS_WORDS:
            numbers = await _contents_pages(doc)
        else:
            numbers = _parse_pages(pages)
    except ValueError:
        result = {"error": f"Could not understand pages {pages!r}. Use e.g. \"2\", \"10-12\" or \"3, 5\"."}
        logger.info("← %s", result)
        return result
    numbers = [n for n in numbers if 1 <= n <= doc.pages]
    if not numbers:
        result = {"error": f"{doc.name} has pages 1 to {doc.pages}."}
        logger.info("← %s", result)
        return result
    note = None
    if len(numbers) > MAX_PAGES_PER_READ:
        note = f"Only the first {MAX_PAGES_PER_READ} pages were returned; ask again for the rest."
        numbers = numbers[:MAX_PAGES_PER_READ]

    rows = await store.get_pages(doc.doc_id, numbers)
    result = {
        "pdf": doc.name,
        "total_pages": doc.pages,
        "pages": [
            {"page": n, "text": _join_chunks([text for page, _, text in rows if page == n])}
            for n in numbers
        ],
    }
    if note:
        result["note"] = note
    for page in result["pages"]:
        logger.info("   %s p.%d (%d chars)", doc.name, page["page"], len(page["text"]))
    logger.info("← %d pages", len(result["pages"]))
    return result


if __name__ == "__main__":
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    logger.info(
        "PDF Q&A MCP server on http://localhost:%d/mcp (uploads: %s, embeddings: %s, vector DB: %s/%s)",
        PORT, UPLOAD_DIR, EMBED_MODEL, QDRANT_URL, QDRANT_COLLECTION,
    )
    mcp.run(transport="streamable-http", host="127.0.0.1", port=PORT)
