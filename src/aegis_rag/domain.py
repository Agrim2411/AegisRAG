from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


def utc_now() -> datetime:
    return datetime.now(UTC)


class IngestRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    source_uri: str = Field(min_length=1, max_length=1000)
    content: str = Field(min_length=1)
    content_type: Literal["text/markdown", "text/plain"] = "text/markdown"
    metadata: dict[str, str] = Field(default_factory=dict, max_length=20)

    @field_validator("title", "source_uri")
    @classmethod
    def strip_required(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value cannot be blank")
        return value


class QueryRequest(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    top_k: int | None = Field(default=None, ge=1, le=20)
    filters: dict[str, str] = Field(default_factory=dict, max_length=10)
    thread_id: str | None = Field(default=None, min_length=3, max_length=100)

    @field_validator("question")
    @classmethod
    def normalize_question(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("question cannot be blank")
        return value


class Chunk(BaseModel):
    id: str
    document_id: str
    tenant_id: str
    ordinal: int
    section: str
    text: str
    content_hash: str
    start_char: int
    end_char: int
    embedding: list[float] = Field(default_factory=list)
    metadata: dict[str, str] = Field(default_factory=dict)


class Document(BaseModel):
    id: str
    tenant_id: str
    title: str
    source_uri: str
    content_type: str
    content_hash: str
    created_at: datetime = Field(default_factory=utc_now)
    metadata: dict[str, str] = Field(default_factory=dict)
    chunks: list[Chunk] = Field(default_factory=list)


class Citation(BaseModel):
    id: str
    document_id: str
    title: str
    section: str
    content_hash: str
    quote: str
    score: float
    source_uri: str | None = None


class RetrievalInfo(BaseModel):
    strategy: str
    candidates: int
    selected: int
    latency_ms: float


class WorkflowInfo(BaseModel):
    engine: str = "langgraph"
    nodes: list[str]
    rewrites: int
    verification_passed: bool
    thread_id: str


class QueryResponse(BaseModel):
    answer: str
    citations: list[Citation]
    retrieval: RetrievalInfo
    grounded: bool
    abstained: bool = False
    request_id: str
    workflow: WorkflowInfo


class IncidentAnalyzeRequest(BaseModel):
    incident_id: str | None = Field(default=None, max_length=100)
    title: str = Field(min_length=3, max_length=300)
    service: str = Field(min_length=1, max_length=100)
    environment: str = Field(default="production", max_length=50)
    symptoms: str = Field(min_length=5, max_length=5000)
    telemetry: list[str] = Field(default_factory=list, max_length=50)
    top_k: int = Field(default=6, ge=1, le=20)


class RootCauseHypothesis(BaseModel):
    rank: int
    hypothesis: str
    confidence: float
    evidence: list[str]


class IncidentReport(BaseModel):
    incident_id: str
    severity: Literal["SEV-1", "SEV-2", "SEV-3"]
    summary: str
    hypotheses: list[RootCauseHypothesis]
    recommended_actions: list[str]
    citations: list[Citation]
    confidence: float
    approval_required: bool = True
    workflow: WorkflowInfo
    request_id: str


class TelemetryEvent(BaseModel):
    id: str
    run_id: str
    scenario_id: str
    tenant_id: str
    service: str
    environment: str
    event_type: Literal["deployment", "metric", "log", "trace"]
    occurred_at: datetime
    name: str
    value: str | float | int
    attributes: dict[str, str | float | int | bool] = Field(default_factory=dict)


class TimelineEntry(BaseModel):
    occurred_at: datetime
    kind: str
    message: str
    event_id: str | None = None


class ScenarioRunRequest(BaseModel):
    scenario_id: str = Field(min_length=3, max_length=100)


class ScenarioSummary(BaseModel):
    id: str
    name: str
    service: str
    description: str
    expected_incident: bool


class ScenarioRunResponse(BaseModel):
    run_id: str
    scenario_id: str
    status: Literal["incident_created", "no_incident"]
    generated_events: int
    alert_triggered: bool
    incident: IncidentReport | None = None
    timeline: list[TimelineEntry]
    expected_outcome_verified: bool


class StoredIncident(BaseModel):
    report: IncidentReport
    scenario_id: str
    run_id: str
    timeline: list[TimelineEntry]


class SearchHit(BaseModel):
    chunk: Chunk
    title: str
    source_uri: str
    score: float
    lexical_score: float = 0.0
    dense_score: float = 0.0
