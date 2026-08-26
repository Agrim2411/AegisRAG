#!/usr/bin/env bash
set -euo pipefail

PORT="${AEGIS_RAG_SMOKE_PORT:-8765}"
DB_FILE="${AEGIS_RAG_SMOKE_DB:-/tmp/aegis-rag-smoke.db}"
rm -f "$DB_FILE" "$DB_FILE-shm" "$DB_FILE-wal"
AEGIS_RAG_DATABASE_URL="sqlite:///$DB_FILE" python3 -m uvicorn aegis_rag.api:app --host 127.0.0.1 --port "$PORT" >/tmp/aegis-rag-smoke.log 2>&1 &
SERVER_PID=$!
trap 'kill "$SERVER_PID" 2>/dev/null || true' EXIT
READY=0
for _ in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:$PORT/readyz" >/dev/null 2>&1; then
    READY=1
    break
  fi
  sleep 0.2
done
if [ "$READY" -ne 1 ]; then
  echo "API failed readiness; server log:" >&2
  sed -n '1,120p' /tmp/aegis-rag-smoke.log >&2
  exit 1
fi
curl -fsS "http://127.0.0.1:$PORT/healthz" | python3 -c 'import json,sys; assert json.load(sys.stdin)["status"] == "ok"'
curl -fsS -X POST "http://127.0.0.1:$PORT/v1/ingest" -H 'content-type: application/json' -H 'x-tenant-id: smoke' -d '{"title":"Smoke policy","source_uri":"smoke://policy","content":"# Policy\n\nSmoke tests verify that audit records are retained for 7 days."}' | python3 -c 'import json,sys; assert json.load(sys.stdin)["chunks"] == 1'
curl -fsS -X POST "http://127.0.0.1:$PORT/v1/query" -H 'content-type: application/json' -H 'x-tenant-id: smoke' -d '{"question":"How long are audit records retained?"}' | python3 -c 'import json,sys; body=json.load(sys.stdin); assert body["citations"]; assert body["request_id"].startswith("req_")'
curl -fsS -X POST "http://127.0.0.1:$PORT/v1/scenarios/run" -H 'content-type: application/json' -H 'x-tenant-id: acme-payments' -d '{"scenario_id":"payments-pool-exhaustion"}' | python3 -c 'import json,sys; body=json.load(sys.stdin); assert body["status"] == "incident_created"; assert body["generated_events"] == 6; assert body["expected_outcome_verified"] is True; assert body["incident"]["workflow"]["verification_passed"] is True'
curl -fsS "http://127.0.0.1:$PORT/metrics" | grep -q 'aegis_rag_queries_total'
echo "AegisRAG smoke test passed"
