# Production stack

| Component | Responsibility | Local fallback |
| --- | --- | --- |
| LangGraph | Stateful orchestration, bounded retries, checkpointed threads | In-memory checkpoint saver |
| LangChain Core | Standard retriever and document contracts | Same path |
| Qdrant | Tenant-filtered dense+sparse retrieval with server-side RRF | SQLite + local RRF/MMR |
| Redis | Tenant-safe response cache | No-op cache |
| SQLite / PostgreSQL | Metadata, audit, and LangGraph checkpoints | SQLite |
| OpenTelemetry + Jaeger | Distributed traces across HTTP and retrieval | JSON logs + metrics |
| FastAPI | Typed API and OpenAPI contract | Same path |

The Docker Compose profile starts the API, Qdrant, Redis, and Jaeger. Qdrant stores dense and sparse vectors under separate names and applies a tenant payload filter to both retrieval legs before RRF fusion.
