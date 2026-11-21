"""PDF uploads.

The frontend uploads a PDF here. It is saved as <UPLOAD_DIR>/<file_id>.pdf, with
<file_id>.json holding its original name. The PDF Q&A MCP server reads it from the
same folder when the model calls ingest_pdf(file_id).
"""

import json
import uuid
from pathlib import Path
from typing import List

from fastapi import APIRouter, HTTPException, UploadFile
from pydantic import BaseModel

from .config import get_settings
from .log import logger

MAX_PDF_BYTES = 20 * 1024 * 1024

router = APIRouter()


class Attachment(BaseModel):
    file_id: str
    name: str


def upload_dir() -> Path:
    path = Path(get_settings().upload_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


@router.post("/api/uploads")
async def upload_pdf(file: UploadFile) -> dict:
    name = Path(file.filename or "document.pdf").name  # drop any folder part
    data = await file.read(MAX_PDF_BYTES + 1)
    if len(data) > MAX_PDF_BYTES:
        raise HTTPException(413, f"PDF is larger than {MAX_PDF_BYTES // (1024 * 1024)} MB")
    if not data.startswith(b"%PDF-"):
        raise HTTPException(415, "Only PDF files can be uploaded")

    file_id = uuid.uuid4().hex[:8]
    folder = upload_dir()
    (folder / f"{file_id}.pdf").write_bytes(data)
    (folder / f"{file_id}.json").write_text(json.dumps({"name": name, "size": len(data)}), encoding="utf-8")

    logger.info("   saved upload %s as %s.pdf (%.1f KB)", name, file_id, len(data) / 1024)
    return {"file_id": file_id, "name": name, "size": len(data)}


def with_attachments(content: str, attachments: List[Attachment]) -> str:
    """Add one line per attached PDF to a message, so the model can see its file_id."""
    lines = [f"[Attached PDF: {a.name}, file_id={a.file_id}]" for a in attachments]
    return "\n".join([content, *lines]) if lines else content
