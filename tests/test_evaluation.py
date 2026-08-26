from aegis_rag.domain import IngestRequest
from aegis_rag.evaluation import meets_gate, run_evaluation
from aegis_rag.ingestion import chunk_document
from aegis_rag.retrieval import HybridRetriever


def test_evaluation_metrics_and_gate(state):
    document = chunk_document(
        IngestRequest(
            title="Retention",
            source_uri="eval://retention",
            content="# Policy\n\nRecords are retained for 365 days.",
        ),
        "acme",
        state.embedder,
    )
    state.store.upsert_document(document)
    result = run_evaluation(
        HybridRetriever(state.store, state.embedder),
        "acme",
        [
            {
                "question": "How long are records retained?",
                "relevant_documents": [],
                "relevant_terms": ["365 days"],
            }
        ],
        3,
    )
    assert result["recall_at_k"] == 1.0
    assert result["mrr"] == 1.0
    assert meets_gate(result, {"recall_at_k": 1.0, "mrr": 1.0, "ndcg_at_k": 1.0})
