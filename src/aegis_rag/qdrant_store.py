"""Qdrant dense+sparse RRF adapter used by the production profile."""

import hashlib
import re
import time
import uuid
from collections import Counter

from .domain import Chunk, Document, SearchHit
from .embeddings import EmbeddingProvider


class QdrantHybridRetriever:
    """Native Qdrant hybrid retrieval with tenant payload filtering."""

    def __init__(
        self,
        url: str,
        collection: str,
        embedder: EmbeddingProvider,
        api_key: str | None = None,
    ) -> None:
        from qdrant_client import QdrantClient

        self.client = (
            QdrantClient(location=":memory:")
            if url == ":memory:"
            else QdrantClient(url=url, api_key=api_key)
        )
        self.collection = collection
        self.embedder = embedder
        self._ensure_collection()

    def _ensure_collection(self) -> None:
        from qdrant_client import models

        if self.client.collection_exists(self.collection):
            return
        self.client.create_collection(
            collection_name=self.collection,
            vectors_config={
                "dense": models.VectorParams(
                    size=self.embedder.dimensions,
                    distance=models.Distance.COSINE,
                )
            },
            sparse_vectors_config={
                "sparse": models.SparseVectorParams(index=models.SparseIndexParams(on_disk=False))
            },
        )
        self.client.create_payload_index(
            collection_name=self.collection,
            field_name="tenant_id",
            field_schema=models.PayloadSchemaType.KEYWORD,
        )

    def index_document(self, document: Document) -> None:
        from qdrant_client import models

        points = []
        for chunk in document.chunks:
            sparse = self._sparse(chunk.text)
            points.append(
                models.PointStruct(
                    id=str(uuid.uuid5(uuid.NAMESPACE_URL, chunk.id)),
                    vector={
                        "dense": chunk.embedding,
                        "sparse": models.SparseVector(**sparse),
                    },
                    payload={
                        "chunk": chunk.model_dump(mode="json", exclude={"embedding"}),
                        "tenant_id": document.tenant_id,
                        "title": document.title,
                        "source_uri": document.source_uri,
                    },
                )
            )
        self.client.upsert(collection_name=self.collection, points=points, wait=True)

    def ready(self) -> bool:
        self.client.get_collection(self.collection)
        return True

    def search(
        self, tenant_id: str, question: str, top_k: int = 4
    ) -> tuple[list[SearchHit], float, int]:
        from qdrant_client import models

        started = time.perf_counter()
        sparse = self._sparse(question)
        query_filter = models.Filter(
            must=[
                models.FieldCondition(
                    key="tenant_id",
                    match=models.MatchValue(value=tenant_id),
                )
            ]
        )
        result = self.client.query_points(
            collection_name=self.collection,
            prefetch=[
                models.Prefetch(
                    query=self.embedder.embed(question),
                    using="dense",
                    filter=query_filter,
                    limit=max(top_k * 3, 20),
                ),
                models.Prefetch(
                    query=models.SparseVector(**sparse),
                    using="sparse",
                    filter=query_filter,
                    limit=max(top_k * 3, 20),
                ),
            ],
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            limit=top_k,
            with_payload=True,
        )
        hits = []
        for point in result.points:
            payload = point.payload or {}
            chunk = Chunk.model_validate(
                {**payload["chunk"], "embedding": self.embedder.embed(payload["chunk"]["text"])}
            )
            hits.append(
                SearchHit(
                    chunk=chunk,
                    title=str(payload.get("title", "Untitled")),
                    source_uri=str(payload.get("source_uri", "qdrant://unknown")),
                    score=float(point.score),
                )
            )
        return hits, (time.perf_counter() - started) * 1000, len(result.points)

    @staticmethod
    def _sparse(text: str) -> dict[str, list]:
        counts = Counter(re.findall(r"[a-z0-9_/-]+", text.lower()))
        values: dict[int, float] = {}
        for token, count in counts.items():
            index = int.from_bytes(hashlib.blake2b(token.encode(), digest_size=4).digest(), "big")
            values[index] = values.get(index, 0.0) + float(count)
        ordered = sorted(values.items())
        return {
            "indices": [index for index, _ in ordered],
            "values": [value for _, value in ordered],
        }
