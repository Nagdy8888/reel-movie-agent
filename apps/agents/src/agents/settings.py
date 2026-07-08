"""Environment-backed configuration for the Reel agent."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentSettings(BaseSettings):
    """Settings for the agent, loaded from environment / .env."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    openai_api_key: str = Field(description="OpenAI API key.")
    openai_chat_model: str = Field(
        default="gpt-4o-mini", description="Chat model used by the agent."
    )
    llm_timeout_seconds: float = Field(default=30.0, description="Per-call LLM timeout in seconds.")
    llm_max_tokens: int = Field(default=1024, description="Maximum tokens per LLM completion.")


def get_settings() -> AgentSettings:
    """Return a fresh AgentSettings instance.

    Kept as a function (not a module-level singleton) so importing the graph in
    LangGraph Studio does not fail if env is loaded slightly later.
    """
    # model_validate loads from env without pyright treating required
    # fields as missing constructor kwargs.
    return AgentSettings.model_validate({})
