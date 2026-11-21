"""Read a PDF's text page by page and split it into overlapping chunks."""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import List

from pypdf import PdfReader


@dataclass
class Chunk:
    page: int  # 1-based page number, so answers can cite it
    text: str


def read_pages(path: Path) -> List[str]:
    """The text of every page (an empty string for pages with no text)."""
    reader = PdfReader(path)
    pages = []
    for page in reader.pages:
        text = page.extract_text() or ""
        # Collapse runs of spaces/tabs and blank lines that PDFs often contain.
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n\s*\n+", "\n\n", text)
        pages.append(text.strip())
    return pages


def split_pages(pages: List[str], size: int, overlap: int) -> List[Chunk]:
    """Split each page into chunks of about `size` characters.

    Neighbouring chunks share `overlap` characters, so a sentence cut at a chunk
    boundary still appears whole in one of them. Chunks never span two pages, so
    each chunk has exactly one page number.
    """
    chunks: List[Chunk] = []
    for page_no, text in enumerate(pages, start=1):
        start = 0
        while start < len(text):
            end = min(start + size, len(text))
            if end < len(text):
                # Prefer to cut at a space rather than in the middle of a word.
                space = text.rfind(" ", start + size // 2, end)
                if space != -1:
                    end = space
            piece = text[start:end].strip()
            if piece:
                chunks.append(Chunk(page=page_no, text=piece))
            if end >= len(text):
                break
            start = max(end - overlap, start + 1)
    return chunks
