from aegis_rag.checkpointing import build_checkpointer
from aegis_rag.domain import IngestRequest
from aegis_rag.generation import GroundedExtractiveProvider
from aegis_rag.ingestion import chunk_document
from aegis_rag.retrieval import HybridRetriever
from aegis_rag.workflow import AgenticRAGWorkflow


def test_langgraph_workflow_retrieves_generates_and_verifies(state):
    document = chunk_document(
        IngestRequest(
            title="Payments runbook",
            source_uri="runbook://payments",
            content=(
                "# Pool exhaustion\n\nHTTP 503 with db_pool_timeout means the "
                "PostgreSQL connection pool is exhausted."
            ),
        ),
        "acme",
        state.embedder,
    )
    state.store.upsert_document(document)
    workflow = AgenticRAGWorkflow(
        HybridRetriever(state.store, state.embedder), GroundedExtractiveProvider()
    )
    result = workflow.run(
        "acme",
        "Why is payments returning HTTP 503 and db_pool_timeout?",
        4,
        "incident-1",
    )
    assert result["trace"] == [
        "retrieve",
        "grade_evidence",
        "generate",
        "verify_citations",
    ]
    assert result["grounded"] is True
    assert result["verification_passed"] is True
    assert "[C1]" in result["answer"]


def test_langgraph_workflow_rewrites_once_then_abstains(state):
    workflow = AgenticRAGWorkflow(
        HybridRetriever(state.store, state.embedder), GroundedExtractiveProvider()
    )
    result = workflow.run("acme", "Unknown production failure", 4, "incident-2")
    assert result["attempts"] == 1
    assert result["trace"].count("retrieve") == 2
    assert result["abstained"] is True
    assert result["verification_passed"] is True


def test_langgraph_state_can_be_checkpointed_to_sqlite(state, tmp_path):
    checkpoint_path = tmp_path / "graph-checkpoints.db"
    workflow = AgenticRAGWorkflow(
        HybridRetriever(state.store, state.embedder),
        GroundedExtractiveProvider(),
        build_checkpointer(str(checkpoint_path)),
    )
    workflow.run("acme", "Unknown production failure", 2, "durable-thread")
    assert checkpoint_path.exists()
    assert checkpoint_path.stat().st_size > 0
