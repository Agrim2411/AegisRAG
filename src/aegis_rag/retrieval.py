import math
import re
import time

from .domain import SearchHit
from .embeddings import EmbeddingProvider, cosine
from .store import SQLiteKnowledgeStore

INJECTION_RE = re.compile(
    r"(?:ignore|disregard|forget)\s+(?:all|any|the)\s+(?:previous|prior|above)\s+instructions|system\s*prompt|developer\s*message",
    re.I,
)
STOPWORDS = {
    "a",
    "an",
    "are",
    "how",
    "is",
    "of",
    "the",
    "what",
    "when",
    "where",
    "which",
    "why",
}
TOKEN_ALIASES = {
    "caused": "cause",
    "causing": "cause",
    "dependencies": "dependency",
    "errors": "error",
    "failed": "failure",
    "failing": "failure",
    "timeouts": "timeout",
}


class HybridRetriever:
    def __init__(self, store: SQLiteKnowledgeStore, embedder: EmbeddingProvider) -> None:
        self.store = store

        self.embedder = embedder

    def search(
        self, tenant_id: str, question: str, top_k: int = 4
    ) -> tuple[list[SearchHit], float, int]:
        started = time.perf_counter()
        query_tokens = _tokens(question)
        query_vector = self.embedder.embed(question)
        rows = self.store.chunks(tenant_id)
        searchable = [
            (row, _tokens(f"{row[1]} {row[1]} {row[0].section} {row[0].text}"))
            for row in rows
            if not INJECTION_RE.search(row[0].text)
        ]
        document_frequency = {
            token: sum(token in set(tokens) for _, tokens in searchable)
            for token in set(query_tokens)
        }
        average_length = sum(len(tokens) for _, tokens in searchable) / max(len(searchable), 1)
        lexical: list[tuple[float, tuple]] = []
        dense: list[tuple[float, tuple]] = []
        for row, tokens in searchable:
            chunk = row[0]
            lexical_score = _bm25(
                query_tokens,
                tokens,
                document_frequency,
                len(searchable),
                average_length,
            )
            dense_score = cosine(query_vector, chunk.embedding)
            lexical.append((lexical_score, row))
            dense.append((dense_score, row))
        lexical.sort(key=lambda item: item[0], reverse=True)
        dense.sort(key=lambda item: item[0], reverse=True)
        lex_rank = {item[1][0].id: rank for rank, item in enumerate(lexical, 1)}
        dense_rank = {item[1][0].id: rank for rank, item in enumerate(dense, 1)}
        scores: dict[str, float] = {}
        rows_by_id = {row[0].id: row for _, row in lexical}
        for chunk_id in rows_by_id:
            scores[chunk_id] = 1 / (60 + lex_rank.get(chunk_id, 10_000)) + 1 / (
                60 + dense_rank.get(chunk_id, 10_000)
            )
        ranked = sorted(scores, key=scores.get, reverse=True)[: max(top_k * 3, top_k)]
        hits = [
            SearchHit(
                chunk=rows_by_id[cid][0],
                title=rows_by_id[cid][1],
                source_uri=rows_by_id[cid][2],
                score=scores[cid],
                lexical_score=next((s for s, row in lexical if row[0].id == cid), 0.0),
                dense_score=next((s for s, row in dense if row[0].id == cid), 0.0),
            )
            for cid in ranked
        ]
        selected = self._mmr(hits, top_k)
        elapsed = (time.perf_counter() - started) * 1000
        return selected, elapsed, len(hits)

    @staticmethod
    def _mmr(hits: list[SearchHit], top_k: int, relevance_weight: float = 0.75) -> list[SearchHit]:
        selected: list[SearchHit] = []
        remaining = hits[:]
        high = max((hit.score for hit in hits), default=1.0)
        low = min((hit.score for hit in hits), default=0.0)

        def normalized_relevance(hit: SearchHit) -> float:
            return (hit.score - low) / max(high - low, 1e-9)

        while remaining and len(selected) < top_k:
            winner = max(
                remaining,
                key=lambda hit: (
                    relevance_weight * normalized_relevance(hit)
                    - (1 - relevance_weight)
                    * max(
                        (
                            max(0.0, cosine(hit.chunk.embedding, prior.chunk.embedding))
                            for prior in selected
                        ),
                        default=0.0,
                    )
                ),
            )
            selected.append(winner)
            remaining.remove(winner)
        return selected


def answer_from_evidence(question: str, hits: list[SearchHit]) -> tuple[str, bool, bool]:
    """Extractive local answerer; evidence is data, never an instruction."""
    if not hits or hits[0].score < 0.012:
        return (
            "I don't have enough evidence in the connected knowledge base "
            "to answer that confidently.",
            False,
            True,
        )
    sentences: list[str] = []
    question_terms = set(_tokens(question))
    for index, hit in enumerate(hits[:3], 1):
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", hit.chunk.text):
            overlap = len(question_terms.intersection(_tokens(sentence)))
            if sentence.strip() and overlap:
                sentences.append(f"{sentence.strip()} [C{index}]")
    if not sentences:
        sentences = [f"The most relevant evidence says: {hits[0].chunk.text[:320].strip()} [C1]"]
    return " ".join(dict.fromkeys(sentences))[:1200], True, False


def _tokens(text: str) -> list[str]:
    tokens: list[str] = []
    for token in re.findall(r"[a-z0-9_/-]+", text.lower()):
        candidates = [token, *re.split(r"[-_/]", token)]
        candidates.extend(
            TOKEN_ALIASES[candidate] for candidate in candidates if candidate in TOKEN_ALIASES
        )
        tokens.extend(candidate for candidate in candidates if candidate not in STOPWORDS)
    return tokens


def _bm25(
    query_tokens: list[str],
    document_tokens: list[str],
    document_frequency: dict[str, int],
    corpus_size: int,
    average_length: float,
) -> float:
    k1, b = 1.5, 0.75
    score = 0.0
    for token in set(query_tokens):
        frequency = document_tokens.count(token)
        if not frequency:
            continue
        inverse_document_frequency = math.log(
            1
            + (corpus_size - document_frequency.get(token, 0) + 0.5)
            / (document_frequency.get(token, 0) + 0.5)
        )
        denominator = frequency + k1 * (1 - b + b * len(document_tokens) / max(average_length, 1))
        score += inverse_document_frequency * (frequency * (k1 + 1)) / denominator
    return score
