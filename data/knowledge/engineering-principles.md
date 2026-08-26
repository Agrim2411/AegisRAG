# Engineering principles

## Retrieval quality

Hybrid retrieval is used because exact identifiers and semantic concepts fail differently. Reciprocal-rank fusion combines lexical and dense rankings, and maximal marginal relevance keeps the final context diverse.

## Delivery quality

Every change to chunking, embeddings, or ranking should run the golden evaluation set. A pull request should not merge when recall, MRR, or nDCG falls below the quality gate.
