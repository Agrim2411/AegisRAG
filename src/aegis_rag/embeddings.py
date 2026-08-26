"""Embedding contracts and a deterministic, dependency-free local provider."""

import hashlib
import math
import re
from typing import Protocol

TOKEN_RE = re.compile(r"[a-z0-9_/-]+", re.IGNORECASE)


class EmbeddingProvider(Protocol):
    dimensions: int

    def embed(self, text: str) -> list[float]: ...


class HashEmbeddingProvider:
    """Signed feature hashing with character n-grams for reproducible local retrieval.

    This is not pretending to be a foundation model. It is a deterministic fallback
    that makes the full system runnable offline and keeps CI independent of API keys.
    """

    def __init__(self, dimensions: int = 256) -> None:
        self.dimensions = dimensions

    def embed(self, text: str) -> list[float]:
        tokens = TOKEN_RE.findall(text.lower())
        features = tokens[:]
        normalized = " ".join(tokens)
        features.extend(normalized[i : i + 3] for i in range(max(0, len(normalized) - 2)))
        vector = [0.0] * self.dimensions
        for feature in features:
            digest = hashlib.blake2b(feature.encode(), digest_size=8).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if digest[4] & 1 else -1.0
            vector[index] += sign
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]


def cosine(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    return sum(a * b for a, b in zip(left, right))
