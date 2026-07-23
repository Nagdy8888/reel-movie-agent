"""Environment-backed configuration for the Reel agent."""

from functools import cached_property
from pathlib import Path
from typing import Literal
from urllib.parse import quote_plus

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Repo root `.env` (docker-compose / phase docs) — works from apps/agents or root.
_ROOT_ENV = Path(__file__).resolve().parents[4] / ".env"


class AgentSettings(BaseSettings):
    """Settings for the agent, loaded from environment / .env."""

    model_config = SettingsConfigDict(
        env_file=(_ROOT_ENV, ".env"),
        extra="ignore",
    )

    openai_api_key: str = Field(description="OpenAI API key.")
    openai_chat_model: str = Field(
        default="gpt-4o-mini", description="Chat model used by the agent."
    )
    openai_embed_model: str = Field(
        default="text-embedding-3-small", description="OpenAI embedding model."
    )
    llm_timeout_seconds: float = Field(
        default=30.0,
        gt=0,
        description="Per-call LLM timeout in seconds.",
    )
    llm_max_tokens: int = Field(
        default=1024,
        ge=1,
        description="Maximum tokens per LLM completion.",
    )
    rag_pg_host: str = Field(description="Host for the AGE+pgvector LightRAG Postgres.")
    rag_pg_port: int = Field(
        default=5432,
        ge=1,
        le=65535,
        description="Port for the LightRAG Postgres.",
    )
    rag_pg_user: str = Field(description="Username for the LightRAG Postgres.")
    rag_pg_password: str = Field(description="Password for the LightRAG Postgres.")
    rag_pg_database: str = Field(description="Database name for the LightRAG Postgres.")
    rag_pg_workspace: str = Field(
        default="reel",
        description="LightRAG POSTGRES_WORKSPACE isolation key.",
    )
    lightrag_working_dir: str = Field(
        default="/data/lightrag",
        description="Working directory for LightRAG logs and local artifacts.",
    )
    tmdb_api_access_token: str = Field(
        default="",
        description="TMDB v4 bearer token used to resolve movie posters during ingestion.",
    )
    subset_size: int = Field(
        default=1000,
        ge=1,
        description="Number of CMU movies to ingest into LightRAG and the UI projection.",
    )
    ingest_concurrency: int = Field(
        default=4,
        ge=1,
        description="Semaphore cap for parallel LightRAG extraction and TMDB poster calls.",
    )
    embedding_dimensions: Literal[1536] = Field(
        default=1536,
        description="Embedding vector size (text-embedding-3-small=1536).",
    )
    retrieval_top_k: int = Field(
        default=5,
        ge=1,
        description="Number of context chunks each LightRAG query returns.",
    )
    rerank_top_k: int = Field(
        default=5,
        ge=1,
        description="Maximum candidates kept after reranking.",
    )
    supabase_db_url: str = Field(
        description=(
            "Postgres URL for LangGraph checkpointer/store and the Movie/Person/Genre "
            "UI projection tables (Supabase)."
        )
    )
    langsmith_tracing: bool = Field(
        default=True, description="Whether LangSmith tracing is enabled."
    )
    langsmith_api_key: str = Field(default="", description="LangSmith API key.")
    langsmith_project: str = Field(
        default="reel-agent", description="LangSmith project name for traces."
    )

    @cached_property
    def rag_db_url(self) -> str:
        """Return an asyncpg DSN for the LightRAG Postgres readiness probe."""
        user = quote_plus(self.rag_pg_user)
        password = quote_plus(self.rag_pg_password)
        return (
            f"postgresql://{user}:{password}@{self.rag_pg_host}:"
            f"{self.rag_pg_port}/{self.rag_pg_database}"
        )


def get_settings() -> AgentSettings:
    """Return a fresh AgentSettings instance.

    Kept as a function (not a module-level singleton) so importing the graph in
    LangGraph Studio does not fail if env is loaded slightly later.
    """
    # model_validate loads from env without pyright treating required
    # fields as missing constructor kwargs.
    return AgentSettings.model_validate({})


def validate_runtime_settings(settings: AgentSettings) -> None:
    """Reject missing or placeholder settings required by agent runtime paths.

    Args:
        settings: Loaded agent settings to validate.

    Raises:
        RuntimeError: If a required OpenAI, LightRAG, or Supabase value is unsafe.
    """
    required = {
        "OPENAI_API_KEY": settings.openai_api_key,
        "RAG_PG_HOST": settings.rag_pg_host,
        "RAG_PG_USER": settings.rag_pg_user,
        "RAG_PG_PASSWORD": settings.rag_pg_password,
        "RAG_PG_DATABASE": settings.rag_pg_database,
        "SUPABASE_DB_URL": settings.supabase_db_url,
    }
    invalid = [
        name
        for name, value in required.items()
        if not value.strip() or "change-me" in value.casefold()
    ]
    if invalid:
        raise RuntimeError(f"Missing/placeholder agent config: {invalid}")
