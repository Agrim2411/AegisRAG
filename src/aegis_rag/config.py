from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AEGIS_RAG_", env_file=".env", extra="ignore")

    env: str = "local"
    database_url: str = "sqlite:///./data/aegis_rag.db"
    embedding_dimensions: int = Field(default=256, ge=32, le=2048)
    top_k: int = Field(default=4, ge=1, le=20)
    max_document_bytes: int = Field(default=2_000_000, ge=1_000, le=20_000_000)
    log_level: str = "INFO"
    qdrant_url: str | None = None
    qdrant_api_key: str | None = None
    qdrant_collection: str = "aegis_incident_knowledge"
    redis_url: str | None = None
    otel_enabled: bool = False
    otel_service_name: str = "aegis-rag-api"
    checkpoint_path: str | None = None
    answer_provider: str = "local"
    llm_model: str = "gpt-5-mini"


@lru_cache
def get_settings() -> Settings:
    return Settings()
