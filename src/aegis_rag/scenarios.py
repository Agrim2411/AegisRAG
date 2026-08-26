"""Deterministic production-incident simulation and alert detection."""

import operator
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

from .domain import (
    IncidentAnalyzeRequest,
    IngestRequest,
    ScenarioRunResponse,
    ScenarioSummary,
    TelemetryEvent,
    TimelineEntry,
)
from .embeddings import EmbeddingProvider
from .incidents import IncidentCommander
from .ingestion import chunk_document
from .store import SQLiteKnowledgeStore


class EventSpec(BaseModel):
    at_seconds: int = Field(ge=0, le=86_400)
    type: Literal["deployment", "metric", "log", "trace"]
    name: str
    value: str | float | int
    attributes: dict[str, str | float | int | bool] = Field(default_factory=dict)


class AlertSpec(BaseModel):
    metric: str
    operator: Literal[">", ">=", "<", "<=", "=="]
    threshold: float
    occurrences: int = Field(default=1, ge=1)


class ExpectedOutcome(BaseModel):
    incident: bool
    relevant_terms: list[str] = Field(default_factory=list)


class ScenarioDefinition(BaseModel):
    id: str
    name: str
    description: str
    tenant_id: str
    service: str
    environment: str = "production"
    knowledge: list[str] = Field(default_factory=list)
    events: list[EventSpec]
    alert: AlertSpec
    expected: ExpectedOutcome


class ScenarioRunner:
    def __init__(
        self,
        store: SQLiteKnowledgeStore,
        embedder: EmbeddingProvider,
        commander: IncidentCommander,
        vector_index=None,
        scenario_dir: str | Path = "data/scenarios",
    ) -> None:
        self.store = store
        self.embedder = embedder
        self.commander = commander
        self.vector_index = vector_index
        self.scenario_dir = Path(scenario_dir)

    def list_scenarios(self, tenant_id: str | None = None) -> list[ScenarioSummary]:
        return [
            ScenarioSummary(
                id=scenario.id,
                name=scenario.name,
                service=scenario.service,
                description=scenario.description,
                expected_incident=scenario.expected.incident,
            )
            for scenario in self._definitions()
            if tenant_id is None or scenario.tenant_id == tenant_id
        ]

    def run(self, tenant_id: str, scenario_id: str, request_id: str) -> ScenarioRunResponse:
        scenario = self._load(scenario_id)
        if scenario.tenant_id != tenant_id:
            raise PermissionError("scenario belongs to another tenant")
        self._seed_knowledge(scenario, tenant_id)
        run_id = "run_" + uuid.uuid4().hex[:12]
        started = datetime.now(UTC).replace(microsecond=0)
        events: list[TelemetryEvent] = []
        timeline: list[TimelineEntry] = []
        alert_triggered_at: datetime | None = None
        for ordinal, spec in enumerate(sorted(scenario.events, key=lambda event: event.at_seconds)):
            event = TelemetryEvent(
                id=f"evt_{uuid.uuid5(uuid.NAMESPACE_URL, f'{run_id}:{ordinal}').hex[:16]}",
                run_id=run_id,
                scenario_id=scenario.id,
                tenant_id=tenant_id,
                service=scenario.service,
                environment=scenario.environment,
                event_type=spec.type,
                occurred_at=started + timedelta(seconds=spec.at_seconds),
                name=spec.name,
                value=spec.value,
                attributes=spec.attributes,
            )
            self.store.append_telemetry(event)
            events.append(event)
            timeline.append(
                TimelineEntry(
                    occurred_at=event.occurred_at,
                    kind=event.event_type,
                    message=f"{event.name}={event.value}",
                    event_id=event.id,
                )
            )
            if alert_triggered_at is None and self._alert_fired(events, scenario.alert):
                alert_triggered_at = event.occurred_at
                timeline.append(
                    TimelineEntry(
                        occurred_at=event.occurred_at,
                        kind="alert.triggered",
                        message=(
                            f"{scenario.alert.metric} {scenario.alert.operator} "
                            f"{scenario.alert.threshold} for "
                            f"{scenario.alert.occurrences} samples"
                        ),
                    )
                )
        if alert_triggered_at is None:
            verified = not scenario.expected.incident
            return ScenarioRunResponse(
                run_id=run_id,
                scenario_id=scenario.id,
                status="no_incident",
                generated_events=len(events),
                alert_triggered=False,
                timeline=timeline,
                expected_outcome_verified=verified,
            )
        incident_id = "INC-SIM-" + run_id.removeprefix("run_").upper()
        telemetry = [
            f"{event.occurred_at.isoformat()} {event.event_type} {event.name}={event.value}"
            for event in events
        ]
        report = self.commander.analyze(
            tenant_id,
            IncidentAnalyzeRequest(
                incident_id=incident_id,
                title=f"{scenario.name} detected in {scenario.service}",
                service=scenario.service,
                environment=scenario.environment,
                symptoms="; ".join(telemetry[-8:]),
                telemetry=telemetry,
                top_k=6,
            ),
            request_id,
        )
        timeline.append(
            TimelineEntry(
                occurred_at=alert_triggered_at + timedelta(seconds=1),
                kind="analysis.completed",
                message=(
                    f"LangGraph verified {len(report.citations)} citations and produced "
                    f"{len(report.hypotheses)} root-cause hypotheses"
                ),
            )
        )
        self.store.save_incident(tenant_id, scenario.id, run_id, report, timeline)
        evidence = " ".join(citation.quote.lower() for citation in report.citations)
        verified = scenario.expected.incident and all(
            term.lower() in evidence for term in scenario.expected.relevant_terms
        )
        return ScenarioRunResponse(
            run_id=run_id,
            scenario_id=scenario.id,
            status="incident_created",
            generated_events=len(events),
            alert_triggered=True,
            incident=report,
            timeline=timeline,
            expected_outcome_verified=verified,
        )

    def _definitions(self) -> list[ScenarioDefinition]:
        return [
            ScenarioDefinition.model_validate(yaml.safe_load(path.read_text()))
            for path in sorted(self.scenario_dir.glob("*.yaml"))
        ]

    def _load(self, scenario_id: str) -> ScenarioDefinition:
        for scenario in self._definitions():
            if scenario.id == scenario_id:
                return scenario
        raise KeyError(f"unknown scenario: {scenario_id}")

    def _seed_knowledge(self, scenario: ScenarioDefinition, tenant_id: str) -> None:
        for source in scenario.knowledge:
            path = Path(source)
            request = IngestRequest(
                title=path.stem.replace("-", " ").title(),
                source_uri=str(path),
                content=path.read_text(),
            )
            document = chunk_document(request, tenant_id, self.embedder)
            inserted = self.store.upsert_document(document)
            if inserted and self.vector_index:
                self.vector_index.index_document(document)

    @staticmethod
    def _alert_fired(events: list[TelemetryEvent], alert: AlertSpec) -> bool:
        comparators = {
            ">": operator.gt,
            ">=": operator.ge,
            "<": operator.lt,
            "<=": operator.le,
            "==": operator.eq,
        }
        matching = [
            event
            for event in events
            if event.event_type == "metric"
            and event.name == alert.metric
            and isinstance(event.value, (int, float))
            and comparators[alert.operator](float(event.value), alert.threshold)
        ]
        return len(matching) >= alert.occurrences
