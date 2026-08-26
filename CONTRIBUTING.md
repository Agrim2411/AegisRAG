# Contributing

1. Create a focused branch and explain the behavior change.
2. Add or update a test, especially for tenant boundaries and retrieval quality.
3. Run `make lint && make test && make eval`.
4. If chunking, embeddings, or ranking changes, include before/after evaluation metrics in the pull request.

Keep provider-specific code behind the existing interfaces. Do not commit credentials, raw customer data, or high-cardinality telemetry labels.
