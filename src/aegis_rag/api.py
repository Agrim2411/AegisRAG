import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import PlainTextResponse

from .cache import NullCache, RedisResponseCache
from .checkpointing import build_checkpointer
from .config import Settings, get_settings
from .domain import (
    Citation,
    IncidentAnalyzeRequest,
    IncidentReport,
    IngestRequest,
    QueryRequest,
    QueryResponse,
    RetrievalInfo,
    ScenarioRunRequest,
    ScenarioRunResponse,
    ScenarioSummary,
    SearchHit,
    StoredIncident,
    WorkflowInfo,
)
from .embeddings import HashEmbeddingProvider
from .evaluation import load_cases, meets_gate, run_evaluation
from .generation import GroundedExtractiveProvider, LangChainOpenAIProvider
from .incidents import IncidentCommander
from .ingestion import chunk_document
from .observability import JsonLogger, Metrics, request_id
from .retrieval import HybridRetriever
from .scenarios import ScenarioRunner
from .store import SQLiteKnowledgeStore
from .telemetry import instrument_fastapi
from .workflow import AgenticRAGWorkflow


class AppState:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.metrics = Metrics()
        self.log = JsonLogger()
        self.embedder = HashEmbeddingProvider(settings.embedding_dimensions)
        self.store = SQLiteKnowledgeStore(settings.database_url)
        self.answerer = (
            LangChainOpenAIProvider(settings.llm_model)
            if settings.answer_provider == "openai"
            else GroundedExtractiveProvider()
        )
        self.vector_index = None
        if settings.qdrant_url:
            from .qdrant_store import QdrantHybridRetriever

            self.vector_index = QdrantHybridRetriever(
                settings.qdrant_url,
                settings.qdrant_collection,
                self.embedder,
                settings.qdrant_api_key,
            )
        self.retriever = self.vector_index or HybridRetriever(self.store, self.embedder)
        self.workflow = AgenticRAGWorkflow(
            self.retriever,
            self.answerer,
            build_checkpointer(settings.checkpoint_path),
        )
        self.incident_commander = IncidentCommander(self.workflow)
        self.scenario_runner = ScenarioRunner(
            self.store,
            self.embedder,
            self.incident_commander,
            self.vector_index,
        )
        self.cache = RedisResponseCache(settings.redis_url) if settings.redis_url else NullCache()


def create_app() -> FastAPI:
    settings = get_settings()
    state = AppState(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        state.log.event("service.started", environment=settings.env)
        yield
        state.log.event("service.stopped")

    app = FastAPI(
        title="AegisRAG Incident Intelligence",
        version="0.2.0",
        description="Agentic, evidence-backed production incident intelligence",
        lifespan=lifespan,
    )
    app.state.lattice = state
    instrument_fastapi(app, settings.otel_service_name, settings.otel_enabled)

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        rid = request.headers.get("x-request-id", request_id())
        started = time.perf_counter()
        response = await call_next(request)
        duration = (time.perf_counter() - started) * 1000
        response.headers["x-request-id"] = rid
        response.headers["x-content-type-options"] = "nosniff"
        state.metrics.inc("http_requests")
        state.metrics.observe("http_latency_ms", duration)
        state.log.event(
            "http.request",
            request_id=rid,
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            latency_ms=round(duration, 2),
        )
        return response

    def tenant(value: str | None) -> str:
        if not value or len(value) > 64 or not value.replace("-", "").replace("_", "").isalnum():
            raise HTTPException(
                status_code=400, detail="x-tenant-id is required and must be alphanumeric"
            )
        return value

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "service": "aegis-rag"}

    @app.get("/readyz")
    async def readyz() -> dict[str, str]:
        try:
            with state.store.connection() as db:
                db.execute("SELECT 1").fetchone()
            if state.vector_index:
                state.vector_index.ready()
            state.cache.ready()
            return {"status": "ready"}
        except Exception as exc:
            raise HTTPException(status_code=503, detail="knowledge store unavailable") from exc

    @app.get("/metrics", response_class=PlainTextResponse)
    async def metrics() -> str:
        return state.metrics.prometheus()

    @app.post("/v1/ingest")
    async def ingest(
        payload: IngestRequest, x_tenant_id: str | None = Header(default=None)
    ) -> dict:
        tenant_id = tenant(x_tenant_id)
        if len(payload.content.encode()) > settings.max_document_bytes:
            raise HTTPException(status_code=413, detail="document exceeds configured byte limit")
        document = chunk_document(payload, tenant_id, state.embedder)
        inserted = state.store.upsert_document(document)
        if inserted and state.vector_index:
            state.vector_index.index_document(document)
        state.metrics.inc("documents_ingested" if inserted else "documents_deduplicated")
        return {
            "document_id": document.id,
            "content_hash": document.content_hash,
            "chunks": len(document.chunks),
            "deduplicated": not inserted,
        }

    @app.get("/v1/documents")
    async def documents(x_tenant_id: str | None = Header(default=None)) -> list[dict]:
        return [
            doc.model_dump(mode="json") for doc in state.store.list_documents(tenant(x_tenant_id))
        ]

    @app.post("/v1/query", response_model=QueryResponse)
    async def query(
        payload: QueryRequest, request: Request, x_tenant_id: str | None = Header(default=None)
    ) -> QueryResponse:
        tenant_id = tenant(x_tenant_id)
        rid = request.headers.get("x-request-id", request_id())
        top_k = payload.top_k or settings.top_k
        cached = state.cache.get(tenant_id, payload.question, top_k)
        if cached:
            state.metrics.inc("cache_hits")
            cached["request_id"] = rid
            cached["workflow"]["nodes"] = ["cache_hit"]
            cached["workflow"]["thread_id"] = payload.thread_id or rid
            return QueryResponse.model_validate(cached)
        thread_id = payload.thread_id or rid
        result = state.workflow.run(tenant_id, payload.question, top_k, thread_id)
        hits = [SearchHit.model_validate(hit) for hit in result.get("hits", [])]
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
        state.metrics.inc("queries")
        state.metrics.inc("abstentions" if result["abstained"] else "grounded_answers")
        state.metrics.observe("retrieval_latency_ms", result["retrieval_latency_ms"])
        response = QueryResponse(
            answer=result["answer"],
            citations=citations,
            retrieval=RetrievalInfo(
                strategy=("qdrant_dense_sparse_rrf" if state.vector_index else "hybrid_rrf_mmr"),
                candidates=result["candidates"],
                selected=len(hits),
                latency_ms=round(result["retrieval_latency_ms"], 3),
            ),
            grounded=result["grounded"],
            abstained=result["abstained"],
            request_id=rid,
            workflow=WorkflowInfo(
                nodes=result["trace"],
                rewrites=result["attempts"],
                verification_passed=result["verification_passed"],
                thread_id=thread_id,
            ),
        )
        state.cache.set(tenant_id, payload.question, top_k, response.model_dump(mode="json"))
        return response

    @app.post("/v1/incidents/analyze", response_model=IncidentReport)
    async def analyze_incident(
        payload: IncidentAnalyzeRequest,
        request: Request,
        x_tenant_id: str | None = Header(default=None),
    ) -> IncidentReport:
        rid = request.headers.get("x-request-id", request_id())
        report = state.incident_commander.analyze(tenant(x_tenant_id), payload, rid)
        state.metrics.inc("incidents_analyzed")
        return report

    @app.get("/v1/scenarios", response_model=list[ScenarioSummary])
    async def scenarios(
        x_tenant_id: str | None = Header(default=None),
    ) -> list[ScenarioSummary]:
        return state.scenario_runner.list_scenarios(tenant(x_tenant_id))

    @app.get("/v1/scenarios/{scenario_id}")
    async def scenario_definition(
        scenario_id: str, x_tenant_id: str | None = Header(default=None)
    ) -> dict:
        tenant_id = tenant(x_tenant_id)
        try:
            scenario = state.scenario_runner.get_scenario(tenant_id, scenario_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        result = scenario.model_dump(mode="json")
        result["source_uri"] = f"data/scenarios/{scenario.id}.yaml"
        result["persistence"] = {
            "database": state.store.path,
            "telemetry_table": "telemetry_events",
            "incident_table": "incidents",
        }
        return result

    @app.post("/v1/scenarios/run", response_model=ScenarioRunResponse)
    async def run_scenario(
        payload: ScenarioRunRequest,
        request: Request,
        x_tenant_id: str | None = Header(default=None),
    ) -> ScenarioRunResponse:
        rid = request.headers.get("x-request-id", request_id())
        try:
            result = state.scenario_runner.run(tenant(x_tenant_id), payload.scenario_id, rid)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        state.metrics.inc("scenarios_run")
        state.metrics.inc(result.status)
        return result

    @app.get("/v1/incidents/{incident_id}", response_model=StoredIncident)
    async def incident(
        incident_id: str, x_tenant_id: str | None = Header(default=None)
    ) -> StoredIncident:
        stored = state.store.get_incident(tenant(x_tenant_id), incident_id)
        if not stored:
            raise HTTPException(status_code=404, detail="incident not found")
        return stored

    @app.post("/v1/evals/run")
    async def evals(
        x_tenant_id: str | None = Header(default=None),
        dataset: str = "data/eval/golden.jsonl",
        top_k: int = 4,
    ) -> dict:
        tenant_id = tenant(x_tenant_id)
        result = run_evaluation(state.retriever, tenant_id, load_cases(dataset), top_k)
        result["gate_passed"] = meets_gate(result)
        return result

    return app


app = create_app()
