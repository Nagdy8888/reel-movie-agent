"""Cached, shared client factories for the agent."""

import logging
import os
from functools import lru_cache
from types import SimpleNamespace

from langchain_openai import ChatOpenAI
from langsmith.wrappers import wrap_openai
from openai import AsyncOpenAI, OpenAI
from pydantic import SecretStr

from agents.settings import get_settings

logger = logging.getLogger("reel.agent")


def configure_langsmith() -> None:
    """Export settings so direct OpenAI and ``@traceable`` calls are traced."""
    settings = get_settings()
    tracing_enabled = settings.langsmith_tracing and bool(settings.langsmith_api_key)
    if settings.langsmith_tracing and not settings.langsmith_api_key:
        logger.warning("LangSmith tracing requested but LANGSMITH_API_KEY is missing")
    os.environ.setdefault("LANGSMITH_TRACING", str(tracing_enabled).lower())
    if settings.langsmith_api_key:
        os.environ.setdefault("LANGSMITH_API_KEY", settings.langsmith_api_key)
    os.environ.setdefault("LANGSMITH_PROJECT", settings.langsmith_project)


class UtilityLLM:
    """Thin sync chat wrapper that never emits LangChain streaming events.

    Used by the router and reranker so the backend SSE stream stays limited to
    the final ``generate`` node.
    """

    def invoke(self, prompt: str) -> SimpleNamespace:
        """Return a chat completion for the given prompt.

        Args:
            prompt: Fully formatted user/system prompt text.

        Returns:
            An object with a ``content`` attribute (OpenAI message text).
        """
        settings = get_settings()
        response = get_sync_openai_client().chat.completions.create(
            model=settings.openai_chat_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=settings.llm_max_tokens,
            timeout=settings.llm_timeout_seconds,
        )
        content = ""
        if response.choices:
            content = response.choices[0].message.content or ""
        return SimpleNamespace(content=content)


@lru_cache(maxsize=1)
def get_chat_model() -> ChatOpenAI:
    """Return the shared chat model with a timeout and token cap.

    Cached so the client (and its HTTP pool) is created once, not per call.
    """
    configure_langsmith()
    settings = get_settings()
    return ChatOpenAI(
        model=settings.openai_chat_model,
        api_key=SecretStr(settings.openai_api_key),
        timeout=settings.llm_timeout_seconds,
        max_completion_tokens=settings.llm_max_tokens,
        temperature=0,
    )


@lru_cache(maxsize=1)
def get_utility_llm() -> UtilityLLM:
    """Return the shared non-streaming LLM for internal utility tasks.

    Cached so the OpenAI client is created once, not per call.
    """
    return UtilityLLM()


@lru_cache(maxsize=1)
def get_sync_openai_client() -> OpenAI:
    """Return a LangSmith-wrapped sync OpenAI client."""
    configure_langsmith()
    settings = get_settings()
    return wrap_openai(
        OpenAI(api_key=settings.openai_api_key, timeout=settings.llm_timeout_seconds)
    )


@lru_cache(maxsize=1)
def get_async_openai_client() -> AsyncOpenAI:
    """Return a LangSmith-wrapped async OpenAI client for LightRAG calls."""
    configure_langsmith()
    settings = get_settings()
    return wrap_openai(
        AsyncOpenAI(api_key=settings.openai_api_key, timeout=settings.llm_timeout_seconds)
    )
