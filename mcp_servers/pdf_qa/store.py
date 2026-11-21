"""Vector store for PDF chunks, backed by Qdrant.

Each chunk is one Qdrant point: its embedding plus a payload with the document id,
PDF name, page number, chunk text, and the document's page and chunk counts.
Qdrant keeps everything on disk (data/qdrant/), so saved PDFs survive restarts.

The rest of the server only uses get() / add() / search() / list() / is_empty(),
so another vector database could replace this file without other changes.
"""

import uuid
from dataclasses import dataclass
from typing import List, Optional, Tuple

from qdrant_client import AsyncQdrantClient, models


@dataclass
class Document:
    doc_id: str
    name: str
    pages: int
    chunks: int


@dataclass
class Passage:
    doc_id: str
    name: str
    page: int
    text: str


def _point_id(doc_id: str, index: int) -> str:
    """Same document + chunk number always gives the same id, so re-saving overwrites."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"pdf_qa/{doc_id}/{index}"))


def _doc_filter(doc_id: str) -> models.Filter:
    return models.Filter(must=[models.FieldCondition(key="doc_id", match=models.MatchValue(value=doc_id))])


def _document(payload: dict) -> Document:
    return Document(payload["doc_id"], payload["name"], payload["pages"], payload["chunks"])


class QdrantStore:
    def __init__(self, url: str, collection: str) -> None:
        self.client = AsyncQdrantClient(url=url)
        self.collection = collection

    async def _ensure_collection(self, vector_size: int) -> None:
        """Create the collection (cosine distance) the first time it is needed."""
        if await self.client.collection_exists(self.collection):
            info = await self.client.get_collection(self.collection)
            existing = info.config.params.vectors.size
            if existing != vector_size:
                raise RuntimeError(
                    f"Collection {self.collection!r} holds {existing}-dimension vectors, but the "
                    f"embedding model returns {vector_size}. Use a new QDRANT_COLLECTION name "
                    "after changing EMBED_MODEL."
                )
            return
        await self.client.create_collection(
            self.collection,
            vectors_config=models.VectorParams(size=vector_size, distance=models.Distance.COSINE),
        )
        # Indexes make filtering by document and listing documents fast.
        await self.client.create_payload_index(self.collection, "doc_id", models.PayloadSchemaType.KEYWORD)
        await self.client.create_payload_index(self.collection, "chunk_index", models.PayloadSchemaType.INTEGER)

    async def get(self, doc_id: str) -> Optional[Document]:
        """The saved document with this id, or None."""
        if not await self.client.collection_exists(self.collection):
            return None
        points, _ = await self.client.scroll(self.collection, scroll_filter=_doc_filter(doc_id), limit=1)
        return _document(points[0].payload) if points else None

    async def add(self, doc: Document, items: List[Tuple[int, str, List[float]]]) -> None:
        """Save a document's chunks: (page, text, vector) for each one."""
        await self._ensure_collection(len(items[0][2]))
        points = [
            models.PointStruct(
                id=_point_id(doc.doc_id, index),
                vector=vector,
                payload={
                    "doc_id": doc.doc_id,
                    "name": doc.name,
                    "pages": doc.pages,
                    "chunks": doc.chunks,
                    "chunk_index": index,
                    "page": page,
                    "text": text,
                },
            )
            for index, (page, text, vector) in enumerate(items)
        ]
        for i in range(0, len(points), 256):  # upload in batches
            await self.client.upsert(self.collection, points=points[i : i + 256], wait=True)

    async def search(self, vector: List[float], top_k: int) -> List[Tuple[float, Passage]]:
        """The top_k chunks most similar to `vector`, best first."""
        response = await self.client.query_points(self.collection, query=vector, limit=top_k, with_payload=True)
        return [
            (p.score, Passage(p.payload["doc_id"], p.payload["name"], p.payload["page"], p.payload["text"]))
            for p in response.points
        ]

    async def list(self) -> List[Document]:
        """All saved documents (one entry per PDF, from each PDF's first chunk)."""
        if not await self.client.collection_exists(self.collection):
            return []
        first_chunks = models.Filter(
            must=[models.FieldCondition(key="chunk_index", match=models.MatchValue(value=0))]
        )
        points, _ = await self.client.scroll(self.collection, scroll_filter=first_chunks, limit=1000)
        return [_document(p.payload) for p in points]

    async def is_empty(self) -> bool:
        if not await self.client.collection_exists(self.collection):
            return True
        return (await self.client.count(self.collection, exact=True)).count == 0
