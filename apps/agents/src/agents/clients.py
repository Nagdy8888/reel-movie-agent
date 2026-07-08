"""Cached, shared client factories for the agent."""

from functools import lru_cache

from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from agents.settings import get_settings


@lru_cache(maxsize=1)
def get_chat_model() -> ChatOpenAI:
    """Return the shared chat model with a timeout and token cap.

    Cached so the client (and its HTTP pool) is created once, not per call.
    """
    settings = get_settings()
    return ChatOpenAI(
        model=settings.openai_chat_model,
        api_key=SecretStr(settings.openai_api_key),
        timeout=settings.llm_timeout_seconds,
        max_completion_tokens=settings.llm_max_tokens,
    )
