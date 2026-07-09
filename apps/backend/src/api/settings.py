"""Environment-backed configuration for the backend."""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Repo root `.env` — works when uvicorn is started from apps/backend or the monorepo root.
_ROOT_ENV = Path(__file__).resolve().parents[4] / ".env"


class BackendSettings(BaseSettings):
    """Settings for the FastAPI backend."""

    model_config = SettingsConfigDict(env_file=(_ROOT_ENV, ".env"), extra="ignore")

    app_env: str = Field(default="dev", description="dev | prod.")
    cors_allow_origins: str = Field(
        default="http://localhost:3000",
        description="Comma-separated allowed CORS origins.",
    )
    langsmith_tracing: bool = Field(
        default=False, description="Enable LangSmith tracing for agent runs."
    )
    langsmith_api_key: str = Field(
        default="", description="LangSmith API key (lsv2_...) used to upload traces."
    )
    langsmith_project: str = Field(
        default="reel-agent", description="LangSmith project traces are grouped under."
    )
    langsmith_endpoint: str = Field(
        default="https://api.smith.langchain.com",
        description="LangSmith API endpoint traces are sent to.",
    )
    supabase_url: str = Field(default="", description="Supabase project URL (auth).")
    supabase_jwt_aud: str = Field(default="authenticated", description="Expected JWT audience.")
    supabase_db_url: str = Field(
        default="", description="Postgres URL for chat persistence (Supabase)."
    )

    def origins(self) -> list[str]:
        """Return the CORS origin allowlist as a list."""
        return [o.strip() for o in self.cors_allow_origins.split(",") if o.strip()]


def get_settings() -> BackendSettings:
    """Return backend settings."""
    return BackendSettings()
