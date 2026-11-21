"""In-memory store for PDF chunks and their embeddings.

Everything lives in this process's memory and is lost when the server stops.
Moving to a vector database later means replacing only this file: keep the same
add() / has() / search() / list() methods.
"""

import math
from dataclasses import dataclass, field
from typing import Dict, List, Tuple


@dataclass
class StoredChunk:
    doc_id: str
    name: str
    page: int
    text: str
    vector: List[float]
    norm: float


@dataclass
class Document:
    doc_id: str
    name: str
    pages: int
    chunks: int


@dataclass
class InMemoryStore:
    documents: Dict[str, Document] = field(default_factory=dict)
    chunks: List[StoredChunk] = field(default_factory=list)

    def has(self, doc_id: str) -> bool:
        return doc_id in self.documents

    def add(self, doc: Document, items: List[Tuple[int, str, List[float]]]) -> None:
        """Save a document's chunks: (page, text, vector) for each one."""
        self.documents[doc.doc_id] = doc
        for page, text, vector in items:
            self.chunks.append(
                StoredChunk(doc.doc_id, doc.name, page, text, vector, _norm(vector))
            )

    def search(self, vector: List[float], top_k: int) -> List[Tuple[float, StoredChunk]]:
        """The top_k chunks most similar to `vector` (cosine similarity), best first."""
        query_norm = _norm(vector)
        scored = [
            (sum(a * b for a, b in zip(vector, c.vector)) / (query_norm * c.norm or 1.0), c)
            for c in self.chunks
        ]
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return scored[:top_k]

    def list(self) -> List[Document]:
        return list(self.documents.values())


def _norm(vector: List[float]) -> float:
    return math.sqrt(sum(x * x for x in vector))
