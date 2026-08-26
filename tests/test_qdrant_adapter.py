import pytest

pytest.importorskip("qdrant_client")

from aegis_rag.domain import IngestRequest
from aegis_rag.embeddings import HashEmbeddingProvider
from aegis_rag.ingestion import chunk_document
from aegis_rag.qdrant_store import QdrantHybridRetriever


def test_qdrant_dense_sparse_rrf_and_tenant_filter():
    embedder = HashEmbeddingProvider(64)
    retriever = QdrantHybridRetriever(":memory:", "test_incidents", embedder)
    acme = chunk_document(
        IngestRequest(
            title="Payments runbook",
            source_uri="runbook://payments",
            content="# Failure\n\nHTTP 503 db_pool_timeout means connection pool exhaustion.",
        ),
        "acme",
        embedder,
    )
    other = chunk_document(
        IngestRequest(
            title="Private runbook",
            source_uri="runbook://private",
            content="# Failure\n\nHTTP 503 private tenant secret.",
        ),
        "other",
        embedder,
    )
    retriever.index_document(acme)
    retriever.index_document(other)
    hits, latency, _ = retriever.search("acme", "HTTP 503 db_pool_timeout", 4)
    assert hits
    assert latency >= 0
    assert all(hit.chunk.tenant_id == "acme" for hit in hits)
    assert hits[0].chunk.document_id == acme.id
