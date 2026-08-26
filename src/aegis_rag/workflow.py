"""Stateful, inspectable agentic RAG workflow powered by LangGraph."""

import re
from typing import Any, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from .domain import SearchHit
from .generation import AnswerProvider
from .langchain_adapter import HybridSearchRetriever
from .retrieval import HybridRetriever


class RAGState(TypedDict, total=False):
    tenant_id: str
    original_question: str
    question: str
    top_k: int
    hits: list[dict]
    retrieval_latency_ms: float
    candidates: int
    attempts: int
    evidence_sufficient: bool
    answer: str
    grounded: bool
    abstained: bool
    verification_passed: bool
    trace: list[str]


class AgenticRAGWorkflow:
    """Retrieve, grade, retry once, generate, then deterministically verify citations."""

    def __init__(
        self,
        retriever: HybridRetriever,
        answerer: AnswerProvider,
        checkpointer: Any | None = None,
    ) -> None:
        self.retriever = retriever
        self.answerer = answerer
        builder = StateGraph(RAGState)
        builder.add_node("retrieve", self._retrieve)
        builder.add_node("grade_evidence", self._grade_evidence)
        builder.add_node("rewrite_query", self._rewrite_query)
        builder.add_node("generate", self._generate)
        builder.add_node("verify_citations", self._verify_citations)
        builder.add_edge(START, "retrieve")
        builder.add_edge("retrieve", "grade_evidence")
        builder.add_conditional_edges(
            "grade_evidence",
            self._route_after_grade,
            {"rewrite": "rewrite_query", "generate": "generate"},
        )
        builder.add_edge("rewrite_query", "retrieve")
        builder.add_edge("generate", "verify_citations")
        builder.add_edge("verify_citations", END)
        self.graph = builder.compile(checkpointer=checkpointer or InMemorySaver())

    def run(self, tenant_id: str, question: str, top_k: int, thread_id: str) -> RAGState:
        initial: RAGState = {
            "tenant_id": tenant_id,
            "original_question": question,
            "question": question,
            "top_k": top_k,
            "attempts": 0,
            "trace": [],
        }
        return self.graph.invoke(
            initial,
            config={"configurable": {"thread_id": f"{tenant_id}:{thread_id}"}},
        )

    def _retrieve(self, state: RAGState) -> RAGState:
        adapter = HybridSearchRetriever(
            engine=self.retriever,
            tenant_id=state["tenant_id"],
            top_k=state["top_k"],
        )
        documents = adapter.invoke(state["question"])
        hits = [document.metadata["search_hit"] for document in documents]
        latency = documents[0].metadata["retrieval_latency_ms"] if documents else 0.0
        candidates = documents[0].metadata["candidate_count"] if documents else 0
        return {
            "hits": hits,
            "retrieval_latency_ms": latency,
            "candidates": candidates,
            "trace": [*state["trace"], "retrieve"],
        }

    def _grade_evidence(self, state: RAGState) -> RAGState:
        hits = [SearchHit.model_validate(hit) for hit in state.get("hits", [])]
        sufficient = bool(hits) and hits[0].score >= 0.012
        return {
            "evidence_sufficient": sufficient,
            "trace": [*state["trace"], "grade_evidence"],
        }

    @staticmethod
    def _route_after_grade(state: RAGState) -> str:
        if not state["evidence_sufficient"] and state["attempts"] < 1:
            return "rewrite"
        return "generate"

    def _rewrite_query(self, state: RAGState) -> RAGState:
        rewritten = (
            f"{state['original_question']} root cause runbook remediation "
            "error code deployment dependency"
        )
        return {
            "question": rewritten,
            "attempts": state["attempts"] + 1,
            "trace": [*state["trace"], "rewrite_query"],
        }

    def _generate(self, state: RAGState) -> RAGState:
        hits = [SearchHit.model_validate(hit) for hit in state.get("hits", [])]
        answer, grounded, abstained = self.answerer.answer(state["original_question"], hits)
        return {
            "answer": answer,
            "grounded": grounded,
            "abstained": abstained,
            "trace": [*state["trace"], "generate"],
        }

    def _verify_citations(self, state: RAGState) -> RAGState:
        cited = {int(value) for value in re.findall(r"\[C(\d+)\]", state["answer"])}
        evidence_count = len(state.get("hits", []))
        valid = state["abstained"] or (
            bool(cited) and all(1 <= citation <= evidence_count for citation in cited)
        )
        update: RAGState = {
            "verification_passed": valid,
            "trace": [*state["trace"], "verify_citations"],
        }
        if not valid:
            update.update(
                answer="I found potentially relevant evidence, but could not verify its citations.",
                grounded=False,
                abstained=True,
            )
        return update
