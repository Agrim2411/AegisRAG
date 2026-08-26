# Operations runbook

## Symptoms: answers are empty or abstain

1. Check `/readyz` and `/metrics`.
2. Confirm the tenant has documents with `GET /v1/documents`.
3. Run the golden evaluation benchmark.
4. Inspect chunk lengths and content hashes; re-ingest only after confirming the source changed.

## Symptoms: latency increased

1. Compare `aegis_rag_retrieval_latency_ms_sum` with `http_latency_ms_sum`.
2. Check candidate count and tenant corpus size.
3. In production, move dense search to ANN and lexical search to an indexed backend before increasing worker count.

## Recovery

The local database is disposable because documents are source-derived. In production, restore metadata and audit storage from backups, then rebuild embeddings from immutable raw content using content hashes.
