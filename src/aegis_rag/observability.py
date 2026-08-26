import json
import logging
import time
import uuid
from collections import defaultdict


class Metrics:
    def __init__(self) -> None:
        self.counters: defaultdict[str, int] = defaultdict(int)
        self.latencies: defaultdict[str, list[float]] = defaultdict(list)

    def inc(self, name: str, amount: int = 1) -> None:
        self.counters[name] += amount

    def observe(self, name: str, milliseconds: float) -> None:
        self.latencies[name].append(milliseconds)

    def prometheus(self) -> str:
        lines = []
        for name, value in sorted(self.counters.items()):
            lines.append(f"aegis_rag_{name}_total {value}")
        for name, values in sorted(self.latencies.items()):
            lines.append(f"aegis_rag_{name}_count {len(values)}")
            lines.append(f"aegis_rag_{name}_sum {sum(values):.3f}")
        return "\n".join(lines) + "\n"


class JsonLogger:
    def __init__(self) -> None:
        self.logger = logging.getLogger("aegis_rag")

    def event(self, event: str, **fields: object) -> None:
        self.logger.info(json.dumps({"event": event, **fields}, default=str, sort_keys=True))


def request_id() -> str:
    return "req_" + uuid.uuid4().hex[:16]


def timer() -> float:
    return time.perf_counter()
