# Platform operations handbook

## Recovery objectives

The service targets a 15 minute recovery point objective and a 60 minute recovery time objective for the default deployment. Raw source documents should be stored in durable object storage and embeddings can be rebuilt from content hashes.

## Readiness

The liveness endpoint only verifies that the process can respond. The readiness endpoint checks the knowledge store and should be used by a load balancer before routing traffic.

## Ingestion

Ingestion is idempotent by tenant, source URI, and SHA-256 content hash. A repeated delivery is acknowledged as a deduplication rather than creating duplicate chunks.
