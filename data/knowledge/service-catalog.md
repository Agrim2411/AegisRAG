# Production service catalog

## Payments API

The Payments Platform team owns `payments-api`. It depends on PostgreSQL, the fraud scoring service, and Kafka topic `payment-events-v2`. Pager escalation is `payments-primary`, then `payments-manager` after fifteen minutes.

## Checkout API

The Commerce Runtime team owns `checkout-api`. It depends on Redis Cluster, catalog, pricing, and payments. The rollback command is a privileged action and requires incident-commander approval.

## Safety policy

The AI incident commander may retrieve evidence, rank hypotheses, and draft actions. It must never execute rollback, failover, database mutation, or customer communication without an authenticated human approval event.
