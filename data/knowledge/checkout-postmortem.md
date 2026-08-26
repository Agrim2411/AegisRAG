# Checkout latency postmortem INC-1042

## Impact

Checkout p99 latency exceeded eight seconds for 27 minutes. Twelve percent of requests timed out, although no customer payment data was lost.

## Root cause

Release `checkout-2026.08.17.3` removed a Redis pipeline and issued one network round trip per cart item. High-cardinality carts amplified the N+1 access pattern and saturated the cache client connection pool.

## Corrective actions

The team restored pipelining, added a load-test case for 100-item carts, and created an alert on cache pool wait time. Rollback remains the approved first mitigation if p99 latency exceeds five seconds after a checkout deployment.
