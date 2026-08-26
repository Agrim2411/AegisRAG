# Security and retention policy

## Auditability

Audit events are retained for 365 days in the default policy. Each event includes the tenant, actor, action, subject, timestamp, and request ID so incident responders can reconstruct a change.

## Tenant isolation

Every document and chunk belongs to exactly one tenant. Query-time filters are mandatory and are applied in the persistence layer before retrieval results are returned.

## Untrusted content

Documents are treated as untrusted evidence. Text that attempts to override system instructions is excluded from retrieval and reported to security telemetry.
