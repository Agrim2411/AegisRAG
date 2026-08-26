import json
import math
from pathlib import Path

from .retrieval import HybridRetriever


def load_cases(path: str | Path) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def run_evaluation(
    retriever: HybridRetriever, tenant_id: str, cases: list[dict], top_k: int = 4
) -> dict:
    recalls: list[float] = []
    reciprocal_ranks: list[float] = []
    ndcgs: list[float] = []
    for case in cases:
        hits, _, _ = retriever.search(tenant_id, case["question"], top_k)
        relevant = set(case.get("relevant_documents", []))
        terms = {term.lower() for term in case.get("relevant_terms", [])}

        def is_relevant(hit) -> bool:
            return hit.chunk.document_id in relevant or any(
                term in hit.chunk.text.lower() for term in terms
            )

        ranks = [index for index, hit in enumerate(hits, 1) if is_relevant(hit)]
        recalls.append(float(bool(ranks)))
        reciprocal_ranks.append(1 / ranks[0] if ranks else 0.0)
        gains = [1 if is_relevant(hit) else 0 for hit in hits]
        dcg = sum(gain / math.log2(index + 1) for index, gain in enumerate(gains, 1))
        ideal_count = max(1, min(sum(1 for hit in hits if is_relevant(hit)), top_k))
        ideal = sum(1 / math.log2(index + 1) for index in range(1, ideal_count + 1))
        ndcgs.append(dcg / ideal if ideal else 0.0)
    result = {
        "cases": len(cases),
        "recall_at_k": round(sum(recalls) / max(len(recalls), 1), 4),
        "mrr": round(sum(reciprocal_ranks) / max(len(reciprocal_ranks), 1), 4),
        "ndcg_at_k": round(sum(ndcgs) / max(len(ndcgs), 1), 4),
        "k": top_k,
    }
    return result


def meets_gate(result: dict, thresholds: dict[str, float] | None = None) -> bool:
    thresholds = thresholds or {"recall_at_k": 0.8, "mrr": 0.65, "ndcg_at_k": 0.65}
    return all(result.get(metric, 0.0) >= threshold for metric, threshold in thresholds.items())
