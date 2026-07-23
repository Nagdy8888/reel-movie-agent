"""Configuration validation tests for production safety controls."""

import pytest

from agents.settings import AgentSettings, validate_runtime_settings
from api.main import _validate_env
from api.settings import BackendSettings


def _agent_settings(**overrides: str) -> AgentSettings:
    """Build complete agent settings with optional test overrides."""
    values = {
        "openai_api_key": "test-openai-key",
        "rag_pg_host": "rag-postgres",
        "rag_pg_user": "lightrag",
        "rag_pg_password": "strong-test-password",
        "rag_pg_database": "lightrag",
        "supabase_db_url": "postgresql://postgres:test@db.example/reel",
        **overrides,
    }
    return AgentSettings.model_validate(values)


def test_cors_wildcard_is_rejected_in_development() -> None:
    """Credentials plus a wildcard origin fail closed in every environment."""
    settings = BackendSettings(app_env="dev", cors_allow_origins="*")

    with pytest.raises(RuntimeError, match="cannot contain"):
        _validate_env(settings)


def test_agent_runtime_rejects_placeholder_secret() -> None:
    """Agent startup validation catches placeholders before the first chat."""
    settings = _agent_settings(rag_pg_password="please-change-me")

    with pytest.raises(RuntimeError, match="RAG_PG_PASSWORD"):
        validate_runtime_settings(settings)


def test_agent_runtime_accepts_complete_configuration() -> None:
    """Complete non-placeholder agent runtime settings pass validation."""
    validate_runtime_settings(_agent_settings())
