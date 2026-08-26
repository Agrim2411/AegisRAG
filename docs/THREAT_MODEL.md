# Threat model

| Threat | Boundary | Mitigation | Follow-up for production |
| --- | --- | --- | --- |
| Cross-tenant data leak | API → store | Required tenant header; tenant predicates in every store query | Signed identity claims and policy engine |
| Prompt injection in a document | Source → answerer | Untrusted-content filter; evidence-only answer contract | Classifier, canary corpus, red-team suite |
| Oversized payload | Client → API | Configured byte limit and Pydantic bounds | Gateway/WAF body limits |
| Duplicate delivery | Queue → ingestion | SHA-256 idempotency key | Durable idempotency/outbox table |
| Sensitive logging | API → telemetry | No question/document text in labels or logs | PII redaction and retention policy |
| Store outage | API → dependency | Readiness probe and stable 503 behavior | Circuit breaker and replica/failover |
| Unsafe remediation | Agent → production | Recommendations only; `approval_required=true` | Signed approval event and scoped tool credentials |
| Checkpoint poisoning | State store → graph | Tenant-prefixed thread IDs and structured state | Encryption, retention, and checkpoint integrity checks |

The highest-risk design rule is simple: retrieved text can contain instructions, but the system must never grant it authority. Any LLM adapter must preserve that invariant.
