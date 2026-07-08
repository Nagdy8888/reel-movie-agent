"""Environment-backed configuration for the Reel agent."""

from pathlib import Path

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
        default="text-embedding-3-large", description="OpenAI embedding model."
    )
    llm_timeout_seconds: float = Field(default=30.0, description="Per-call LLM timeout in seconds.")
    llm_max_tokens: int = Field(default=1024, description="Maximum tokens per LLM completion.")
    neo4j_uri: str = Field(description="Neo4j Bolt URI.")
    neo4j_username: str = Field(default="neo4j", description="Neo4j username.")
    neo4j_password: str = Field(description="Neo4j password.")
    neo4j_database: str = Field(default="neo4j", description="Neo4j database name.")
    vector_index_name: str = Field(
        default="movie_plot_embeddings", description="Neo4j vector index name."
    )
    embedding_dimensions: int = Field(
        default=3072, description="Embedding vector size (text-embedding-3-large=3072)."
    )


def get_settings() -> AgentSettings:
    """Return a fresh AgentSettings instance.

    Kept as a function (not a module-level singleton) so importing the graph in
    LangGraph Studio does not fail if env is loaded slightly later.
    """
    # model_validate loads from env without pyright treating required
    # fields as missing constructor kwargs.
    return AgentSettings.model_validate({})
