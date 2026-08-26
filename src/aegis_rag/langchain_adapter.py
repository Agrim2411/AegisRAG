"""LangChain interoperability without hiding the custom retrieval algorithm."""

from typing import Any

from langchain_core.documents import Document as LangChainDocument
from langchain_core.retrievers import BaseRetriever
from pydantic import ConfigDict


class HybridSearchRetriever(BaseRetriever):
    """Expose AegisRAG's hybrid engine through LangChain's retriever contract."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    engine: Any
    tenant_id: str
    top_k: int = 4

    def _get_relevant_documents(
        self, query: str, *, run_manager: Any = None
    ) -> list[LangChainDocument]:
        hits, latency_ms, candidates = self.engine.search(self.tenant_id, query, self.top_k)
        return [
            LangChainDocument(
                page_content=hit.chunk.text,
                metadata={
                    "search_hit": hit.model_dump(mode="json"),
                    "retrieval_latency_ms": latency_ms,
                    "candidate_count": candidates,
                    "document_id": hit.chunk.document_id,
                    "section": hit.chunk.section,
                },
            )
            for hit in hits
        ]
