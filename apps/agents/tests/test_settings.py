"""Tests for LightRAG agent settings."""

from agents.settings import AgentSettings


def _settings() -> AgentSettings:
    """Build isolated settings without relying on the developer's .env."""
    return AgentSettings.model_validate(
        {
            "openai_api_key": "test-openai",
            "rag_pg_host": "rag-postgres",
            "rag_pg_port": 5432,
            "rag_pg_user": "rag user",
            "rag_pg_password": "p@ss/word",
            "rag_pg_database": "lightrag",
            "supabase_db_url": "postgresql://example.invalid/postgres",
        }
    )


def test_rag_db_url_percent_encodes_credentials() -> None:
    """The readiness DSN safely quotes Postgres usernames and passwords."""
    settings = _settings()
    assert settings.rag_db_url == ("postgresql://rag+user:p%40ss%2Fword@rag-postgres:5432/lightrag")


def test_lightrag_defaults_match_fixed_workspace_and_subset() -> None:
    """Workspace, embedding size, concurrency, and subset defaults match the plan."""
    fields = AgentSettings.model_fields
    assert fields["rag_pg_workspace"].default == "reel"
    assert fields["embedding_dimensions"].default == 1536
    assert fields["subset_size"].default == 1000
    assert fields["ingest_concurrency"].default == 4
