"""Cached, shared client factories for the agent."""

from functools import lru_cache

import neo4j
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


@lru_cache(maxsize=1)
def get_neo4j_driver() -> neo4j.Driver:
    """Return the shared, pooled Neo4j driver.

    Cached so a single connection pool is reused across the process. Callers
    must NOT close it per request; it is closed on process shutdown.

    Auth uses AgentSettings.neo4j_username (typically the admin `neo4j` user on
    Community/Aura Free). Read-only access is enforced at the app layer in
    Phase 4 via execute_read + a write-clause guard; on Enterprise/Aura Pro,
    prefer a dedicated read-only role for this driver instead.
    """
    settings = get_settings()
    return neo4j.GraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_username, settings.neo4j_password),
    )
