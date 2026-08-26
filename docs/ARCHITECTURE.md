# Architecture decision record

## Context

Generic RAG demos conflate indexing, retrieval, generation, and evaluation in one notebook. A production incident system must also explain control flow, retries, safety decisions, and evidence quality. AegisRAG keeps each concern independently testable.

## Decisions

### Executable synthetic enterprise

YAML scenarios generate causal deployment, metric, log, and trace sequences for isolated tenants. Events are persisted before alert evaluation. An incident opens only after the configured number of threshold-violating samples, and a healthy control scenario verifies false-positive suppression. Each detected incident is analyzed, stored, and checked against expected evidence.

### Offline-first reference runtime

The reference path uses SQLite and a deterministic hashing embedder. It is fast enough for a local demo and reproducible in CI. The interfaces in `embeddings.py`, `store.py`, and `generation.py` are the seams for production adapters.

### Stateful orchestration with bounded autonomy

LangGraph checkpoints each incident thread and makes retrieve, grade, rewrite, generate, and verify explicit nodes. The query rewrite is limited to one attempt; weak evidence then produces an abstention. This bounds cost and tail latency during an outage.

### Hybrid retrieval before generation

Exact identifiers, deployment SHAs, service names, and error codes are poorly served by semantic similarity alone. The local engine fuses BM25-style and dense rankers with RRF before normalized MMR selection. Qdrant performs tenant-filtered dense+sparse RRF in the production profile.

### Evidence is untrusted data

The retrieval pipeline filters known instruction-override patterns. The LangChain/OpenAI provider labels documents as quoted evidence and returns structured citation IDs. A deterministic graph node verifies those IDs against retrieved evidence before the answer can be marked grounded.

### Diagnosis is separated from execution

The incident workflow ranks hypotheses and proposes remediation, but `approval_required` remains true. Rollback, failover, database mutation, and customer communication are outside the autonomous graph and require an authenticated approval event.

### Deterministic IDs and content hashes

Document identity includes tenant, source URI, and content hash. This makes ingestion naturally idempotent and allows a future re-index job to prove which source produced an embedding.

## Scaling path

1. Move raw documents to object storage and publish ingestion events to a durable queue.
2. Replace SQLite metadata and checkpoints with PostgreSQL and an async connection pool.
3. Add service-specific telemetry connectors and a temporal correlation index.
4. Add token budgets, streaming graph events, circuit breakers, and per-tenant quotas.
5. Use an outbox for audit delivery and signed approval events for privileged tools.

## Non-goals

The local reference is not a benchmark of foundation-model quality, a replacement for a security review, or a multi-node transaction coordinator. Its purpose is to make the reliability boundaries visible and executable.
