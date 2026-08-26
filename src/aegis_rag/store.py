import json
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from .domain import Chunk, Document


class SQLiteKnowledgeStore:
    """Small durable store; every public query carries the tenant predicate."""

    def __init__(self, database_url: str) -> None:
        path = database_url.removeprefix("sqlite:///")
        self.path = path
        if path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self._init_schema()

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _init_schema(self) -> None:
        with self.connection() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, title TEXT NOT NULL,
                    source_uri TEXT NOT NULL, content_type TEXT NOT NULL,
                    content_hash TEXT NOT NULL, created_at TEXT NOT NULL, metadata TEXT NOT NULL,
                    UNIQUE(tenant_id, source_uri, content_hash)
                );
                CREATE TABLE IF NOT EXISTS chunks (
                    id TEXT PRIMARY KEY, document_id TEXT NOT NULL, tenant_id TEXT NOT NULL,
                    ordinal INTEGER NOT NULL, section TEXT NOT NULL, text TEXT NOT NULL,
                    content_hash TEXT NOT NULL, start_char INTEGER NOT NULL,
                    end_char INTEGER NOT NULL,
                    embedding TEXT NOT NULL, metadata TEXT NOT NULL,
                    FOREIGN KEY(document_id) REFERENCES documents(id)
                );
                CREATE INDEX IF NOT EXISTS chunks_tenant_idx ON chunks(tenant_id);
                CREATE INDEX IF NOT EXISTS documents_tenant_idx ON documents(tenant_id);
                CREATE TABLE IF NOT EXISTS audit_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, tenant_id TEXT NOT NULL,
                    action TEXT NOT NULL, subject_id TEXT, created_at TEXT NOT NULL,
                    details TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS telemetry_events (
                    id TEXT PRIMARY KEY, run_id TEXT NOT NULL, scenario_id TEXT NOT NULL,
                    tenant_id TEXT NOT NULL, service TEXT NOT NULL, environment TEXT NOT NULL,
                    event_type TEXT NOT NULL, occurred_at TEXT NOT NULL, name TEXT NOT NULL,
                    value TEXT NOT NULL, attributes TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS telemetry_tenant_run_idx
                    ON telemetry_events(tenant_id, run_id, occurred_at);
                CREATE TABLE IF NOT EXISTS incidents (
                    id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, scenario_id TEXT NOT NULL,
                    run_id TEXT NOT NULL, report TEXT NOT NULL, timeline TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS incidents_tenant_idx
                    ON incidents(tenant_id, created_at);
            """)

    def upsert_document(self, document: Document) -> bool:
        with self.connection() as db:
            existing = db.execute(
                "SELECT id FROM documents WHERE tenant_id=? AND source_uri=? AND content_hash=?",
                (document.tenant_id, document.source_uri, document.content_hash),
            ).fetchone()
            if existing:
                return False
            db.execute(
                "INSERT INTO documents VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    document.id,
                    document.tenant_id,
                    document.title,
                    document.source_uri,
                    document.content_type,
                    document.content_hash,
                    document.created_at.isoformat(),
                    json.dumps(document.metadata),
                ),
            )
            db.executemany(
                "INSERT INTO chunks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        c.id,
                        c.document_id,
                        c.tenant_id,
                        c.ordinal,
                        c.section,
                        c.text,
                        c.content_hash,
                        c.start_char,
                        c.end_char,
                        json.dumps(c.embedding),
                        json.dumps(c.metadata),
                    )
                    for c in document.chunks
                ],
            )
            self._audit(
                db,
                document.tenant_id,
                "document.ingested",
                document.id,
                {"chunks": len(document.chunks)},
            )
            return True

    def list_documents(self, tenant_id: str) -> list[Document]:
        with self.connection() as db:
            rows = db.execute(
                "SELECT * FROM documents WHERE tenant_id=? ORDER BY created_at DESC", (tenant_id,)
            ).fetchall()
        return [self._document(row) for row in rows]

    def chunks(self, tenant_id: str) -> list[tuple[Chunk, str, str]]:
        with self.connection() as db:
            rows = db.execute(
                "SELECT c.*, d.title, d.source_uri FROM chunks c "
                "JOIN documents d ON d.id=c.document_id "
                "WHERE c.tenant_id=? ORDER BY c.document_id, c.ordinal",
                (tenant_id,),
            ).fetchall()
        return [(self._chunk(row), row["title"], row["source_uri"]) for row in rows]

    def audit(self, tenant_id: str) -> list[dict[str, str]]:
        with self.connection() as db:
            rows = db.execute(
                "SELECT * FROM audit_events WHERE tenant_id=? ORDER BY id DESC", (tenant_id,)
            ).fetchall()
        return [dict(row) for row in rows]

    def append_telemetry(self, event) -> None:
        with self.connection() as db:
            db.execute(
                "INSERT INTO telemetry_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    event.id,
                    event.run_id,
                    event.scenario_id,
                    event.tenant_id,
                    event.service,
                    event.environment,
                    event.event_type,
                    event.occurred_at.isoformat(),
                    event.name,
                    json.dumps(event.value),
                    json.dumps(event.attributes),
                ),
            )

    def save_incident(
        self,
        tenant_id: str,
        scenario_id: str,
        run_id: str,
        report,
        timeline,
    ) -> None:
        with self.connection() as db:
            db.execute(
                "INSERT INTO incidents VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    report.incident_id,
                    tenant_id,
                    scenario_id,
                    run_id,
                    report.model_dump_json(),
                    json.dumps([entry.model_dump(mode="json") for entry in timeline]),
                    datetime.now(UTC).isoformat(),
                ),
            )
            self._audit(
                db,
                tenant_id,
                "incident.created",
                report.incident_id,
                {"scenario_id": scenario_id, "run_id": run_id},
            )

    def get_incident(self, tenant_id: str, incident_id: str):
        from .domain import IncidentReport, StoredIncident, TimelineEntry

        with self.connection() as db:
            row = db.execute(
                "SELECT * FROM incidents WHERE tenant_id=? AND id=?",
                (tenant_id, incident_id),
            ).fetchone()
        if not row:
            return None
        return StoredIncident(
            report=IncidentReport.model_validate_json(row["report"]),
            scenario_id=row["scenario_id"],
            run_id=row["run_id"],
            timeline=[TimelineEntry.model_validate(entry) for entry in json.loads(row["timeline"])],
        )

    @staticmethod
    def _audit(
        db: sqlite3.Connection, tenant_id: str, action: str, subject_id: str | None, details: dict
    ) -> None:
        db.execute(
            "INSERT INTO audit_events(tenant_id, action, subject_id, created_at, "
            "details) VALUES (?, ?, ?, ?, ?)",
            (
                tenant_id,
                action,
                subject_id,
                datetime.now(UTC).isoformat(),
                json.dumps(details),
            ),
        )

    @staticmethod
    def _chunk(row: sqlite3.Row) -> Chunk:
        return Chunk(
            id=row["id"],
            document_id=row["document_id"],
            tenant_id=row["tenant_id"],
            ordinal=row["ordinal"],
            section=row["section"],
            text=row["text"],
            content_hash=row["content_hash"],
            start_char=row["start_char"],
            end_char=row["end_char"],
            embedding=json.loads(row["embedding"]),
            metadata=json.loads(row["metadata"]),
        )

    @staticmethod
    def _document(row: sqlite3.Row) -> Document:
        return Document(
            id=row["id"],
            tenant_id=row["tenant_id"],
            title=row["title"],
            source_uri=row["source_uri"],
            content_type=row["content_type"],
            content_hash=row["content_hash"],
            created_at=datetime.fromisoformat(row["created_at"]),
            metadata=json.loads(row["metadata"]),
        )
