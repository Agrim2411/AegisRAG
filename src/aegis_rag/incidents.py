"""Domain service for evidence-backed production incident analysis."""

import uuid

from .domain import (
    Citation,
    IncidentAnalyzeRequest,
    IncidentReport,
    RootCauseHypothesis,
    SearchHit,
    WorkflowInfo,
)
from .workflow import AgenticRAGWorkflow


class IncidentCommander:
    def __init__(self, workflow: AgenticRAGWorkflow) -> None:
        self.workflow = workflow

    def analyze(
        self, tenant_id: str, payload: IncidentAnalyzeRequest, request_id: str
    ) -> IncidentReport:
        incident_id = payload.incident_id or "inc_" + uuid.uuid4().hex[:12]
        telemetry = " ".join(payload.telemetry)
        question = (
            f"Production incident in {payload.service} ({payload.environment}). "
            f"{payload.title}. Symptoms: {payload.symptoms}. Telemetry: {telemetry}. "
            "Identify the most likely root cause and the safest remediation steps."
        )
        state = self.workflow.run(tenant_id, question, payload.top_k, incident_id)
        hits = [SearchHit.model_validate(hit) for hit in state.get("hits", [])]
        citations = [
            Citation(
                id=f"C{index}",
                document_id=hit.chunk.document_id,
                title=hit.title,
                section=hit.chunk.section,
                content_hash=hit.chunk.content_hash,
                quote=hit.chunk.text[:500],
                score=round(hit.score, 6),
                source_uri=hit.source_uri,
            )
            for index, hit in enumerate(hits, 1)
        ]
        hypothesis_candidates = sorted(
            enumerate(hits, 1),
            key=lambda item: self._hypothesis_priority(item[1]),
            reverse=True,
        )[:3]
        hypotheses = [
            RootCauseHypothesis(
                rank=rank,
                hypothesis=(
                    f"The incident is consistent with the failure mode documented in "
                    f"{hit.title} / {hit.chunk.section}."
                ),
                confidence=round(max(0.0, min(0.99, hit.score * 25)), 2),
                evidence=[f"C{citation_index}"],
            )
            for rank, (citation_index, hit) in enumerate(hypothesis_candidates, 1)
        ]
        confidence = hypotheses[0].confidence if hypotheses else 0.0
        return IncidentReport(
            incident_id=incident_id,
            severity=self._severity(payload),
            summary=state["answer"],
            hypotheses=hypotheses,
            recommended_actions=self._actions(citations),
            citations=citations,
            confidence=confidence,
            approval_required=True,
            workflow=WorkflowInfo(
                nodes=state["trace"],
                rewrites=state["attempts"],
                verification_passed=state["verification_passed"],
                thread_id=incident_id,
            ),
            request_id=request_id,
        )

    @staticmethod
    def _severity(payload: IncidentAnalyzeRequest) -> str:
        text = f"{payload.title} {payload.symptoms}".lower()
        if any(term in text for term in ("outage", "data loss", "all requests", "unavailable")):
            return "SEV-1"
        if any(term in text for term in ("latency", "error rate", "degraded", "timeout")):
            return "SEV-2"
        return "SEV-3"

    @staticmethod
    def _actions(citations: list[Citation]) -> list[str]:
        if not citations:
            return ["Escalate to the service owner; the knowledge base lacks verified evidence."]
        return [
            f"Validate the leading hypothesis against [{citations[0].id}] before changing state.",
            "Compare the incident start time with the latest deployment and dependency changes.",
            "Require human approval for rollback, failover, or data-repair actions.",
        ]

    @staticmethod
    def _hypothesis_priority(hit: SearchHit) -> float:
        label = f"{hit.title} {hit.chunk.section}".lower()
        priority = hit.score
        if any(term in label for term in ("root cause", "exhaustion", "failure")):
            priority += 3
        if any(term in label for term in ("runbook", "postmortem")):
            priority += 1
        if any(term in label for term in ("catalog", "ownership", "safety")):
            priority -= 2
        return priority
