# Payments API incident runbook

## Connection pool exhaustion

The payments API returns HTTP 503 and reports `db_pool_timeout` when PostgreSQL connections are exhausted. A deployment that increases request concurrency without increasing the pool is a common trigger. Confirm active connections, queue depth, and the deployment timestamp before changing capacity.

## Safe remediation

First stop the rollout and reduce application concurrency. If saturation continues, roll back the most recent deployment after incident-commander approval. Increasing the database connection limit is not the first response because it can move saturation into PostgreSQL.

## Verification

Recovery requires the HTTP 503 rate to remain below one percent and pool wait time below 100 milliseconds for ten minutes. Record the deployment SHA and query evidence in the incident timeline.
