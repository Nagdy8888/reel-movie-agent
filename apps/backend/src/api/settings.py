"""Environment-backed configuration for the backend."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class BackendSettings(BaseSettings):
    """Settings for the FastAPI backend."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = Field(default="dev", description="dev | prod.")
    cors_allow_origins: str = Field(
        default="http://localhost:3000",
        description="Comma-separated allowed CORS origins.",
    )
    supabase_url: str = Field(default="", description="Supabase project URL (auth).")
    supabase_jwt_aud: str = Field(default="authenticated", description="Expected JWT audience.")

    def origins(self) -> list[str]:
        """Return the CORS origin allowlist as a list."""
        return [o.strip() for o in self.cors_allow_origins.split(",") if o.strip()]


def get_settings() -> BackendSettings:
    """Return backend settings."""
    return BackendSettings()
