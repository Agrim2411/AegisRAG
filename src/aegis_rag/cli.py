import argparse
import json
import sys

from .api import AppState
from .config import get_settings
from .domain import IngestRequest
from .evaluation import load_cases, meets_gate, run_evaluation
from .ingestion import chunk_document


def main() -> None:
    parser = argparse.ArgumentParser(prog="aegis-rag")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("demo")
    evaluation = sub.add_parser("eval")
    evaluation.add_argument("--dataset", default="data/eval/golden.jsonl")
    simulation = sub.add_parser("simulate")
    simulation.add_argument("--scenario", default="payments-pool-exhaustion")
    simulation.add_argument("--tenant", default="acme-payments")
    args = parser.parse_args()
    state = AppState(get_settings())
    _seed_sample_corpus(state)
    if args.command == "demo":
        hits, latency, candidates = state.retriever.search(
            "acme", "How long are audit events retained?", 4
        )
        print(
            json.dumps(
                {
                    "answer": state.answerer.answer("How long are audit events retained?", hits)[0],
                    "citations": [hit.chunk.id for hit in hits],
                    "latency_ms": round(latency, 2),
                    "candidates": candidates,
                },
                indent=2,
            )
        )
    elif args.command == "eval":
        result = run_evaluation(state.retriever, "acme", load_cases(args.dataset))
        result["gate_passed"] = meets_gate(result)
        print(json.dumps(result, indent=2))
        if not result["gate_passed"]:
            sys.exit(1)
    else:
        result = state.scenario_runner.run(
            args.tenant,
            args.scenario,
            "req_cli_simulation",
        )
        print(result.model_dump_json(indent=2))
        if not result.expected_outcome_verified:
            sys.exit(1)


def _seed_sample_corpus(state: AppState) -> None:
    from pathlib import Path

    for path in Path("data/knowledge").glob("*.md"):
        request = IngestRequest(
            title=path.stem.replace("-", " ").title(),
            source_uri=str(path),
            content=path.read_text(),
        )
        document = chunk_document(request, "acme", state.embedder)
        state.store.upsert_document(document)
