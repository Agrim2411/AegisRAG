from aegis_rag.domain import IngestRequest
from aegis_rag.ingestion import chunk_document


def test_chunking_preserves_sections_and_hashes(state):
    document = chunk_document(
        IngestRequest(
            title="Policy", source_uri="file://policy", content="# One\n\nAlpha\n\n## Two\n\nBeta"
        ),
        "tenant-a",
        state.embedder,
    )
    assert [chunk.section for chunk in document.chunks] == ["One", "Two"]
    assert document.content_hash.startswith("sha256:")
    assert all(chunk.embedding for chunk in document.chunks)
    assert all(chunk.tenant_id == "tenant-a" for chunk in document.chunks)


def test_ingestion_is_idempotent(state):
    request = IngestRequest(
        title="Policy", source_uri="file://policy", content="# Policy\n\nSame content"
    )
    document = chunk_document(request, "tenant-a", state.embedder)
    assert state.store.upsert_document(document) is True
    assert state.store.upsert_document(document) is False
    assert len(state.store.list_documents("tenant-a")) == 1
