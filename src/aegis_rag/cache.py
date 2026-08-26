"""Tenant-safe response caching with an optional Redis production adapter."""

import hashlib
import json
from typing import Protocol


class ResponseCache(Protocol):
    def get(self, tenant_id: str, question: str, top_k: int) -> dict | None: ...

    def set(self, tenant_id: str, question: str, top_k: int, value: dict) -> None: ...

    def ready(self) -> bool: ...


class NullCache:
    def get(self, tenant_id: str, question: str, top_k: int) -> None:
        return None

    def set(self, tenant_id: str, question: str, top_k: int, value: dict) -> None:
        return None

    def ready(self) -> bool:
        return True


class RedisResponseCache:
    def __init__(self, redis_url: str, ttl_seconds: int = 300) -> None:
        from redis import Redis

        self.client = Redis.from_url(redis_url, decode_responses=True)
        self.ttl_seconds = ttl_seconds

    @staticmethod
    def _key(tenant_id: str, question: str, top_k: int) -> str:
        digest = hashlib.sha256(f"{tenant_id}|{top_k}|{question}".encode()).hexdigest()
        return f"aegis:rag:{digest}"

    def get(self, tenant_id: str, question: str, top_k: int) -> dict | None:
        value = self.client.get(self._key(tenant_id, question, top_k))
        return json.loads(value) if value else None

    def set(self, tenant_id: str, question: str, top_k: int, value: dict) -> None:
        self.client.setex(
            self._key(tenant_id, question, top_k),
            self.ttl_seconds,
            json.dumps(value),
        )

    def ready(self) -> bool:
        return bool(self.client.ping())
