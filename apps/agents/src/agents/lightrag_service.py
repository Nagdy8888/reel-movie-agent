"""Cached LightRAG instance backed by AGE+pgvector Postgres."""

from __future__ import annotations

import os
from typing import Any, Literal, cast

import asyncpg
import numpy as np
from lightrag import LightRAG, QueryParam
from lightrag.kg.shared_storage import initialize_pipeline_status
from lightrag.utils import wrap_embedding_func_with_attrs
from openai.types.chat import ChatCompletionMessageParam

from agents.clients import get_async_openai_client
from agents.settings import get_settings

_rag: LightRAG | None = None


def _configure_postgres_env() -> None:
    """Set the POSTGRES_* env vars LightRAG's PG storages read.

    Centralized here so business code never scatters ``os.getenv`` calls;
    settings remain the source of truth.
    """
    settings = get_settings()
    os.environ.update(
        {
            "POSTGRES_HOST": settings.rag_pg_host,
            "POSTGRES_PORT": str(settings.rag_pg_port),
            "POSTGRES_USER": settings.rag_pg_user,
            "POSTGRES_PASSWORD": settings.rag_pg_password,
            "POSTGRES_DATABASE": settings.rag_pg_database,
            "POSTGRES_WORKSPACE": settings.rag_pg_workspace,
        }
    )


@wrap_embedding_func_with_attrs(embedding_dim=1536, max_token_size=8192)
async def _embed(texts: list[str]) -> np.ndarray:
    """Embed texts with the configured OpenAI embedding model.

    Args:
        texts: Batched strings to embed.

    Returns:
        A float32 numpy array of shape ``(len(texts), embedding_dim)``.
    """
    settings = get_settings()
    client = get_async_openai_client()
    response = await client.embeddings.create(
        model=settings.openai_embed_model,
        input=texts,
        timeout=settings.llm_timeout_seconds,
    )
    vectors = [item.embedding for item in response.data]
    return np.array(vectors, dtype=np.float32)


async def _llm(
    prompt: str,
    system_prompt: str | None = None,
    history_messages: list[dict[str, Any]] | None = None,
    **kwargs: Any,
) -> str:
    """Bounded chat completion used by LightRAG entity extraction / query.

    Args:
        prompt: User prompt text from LightRAG.
        system_prompt: Optional system prompt.
        history_messages: Optional prior chat turns.
        **kwargs: Extra LightRAG kwargs (ignored except known OpenAI fields).

    Returns:
        Assistant message content, or an empty string on an empty response.
    """
    del kwargs  # LightRAG may pass hashing_kv etc.; ignore unused.
    settings = get_settings()
    messages: list[ChatCompletionMessageParam] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    for item in history_messages or []:
        role = str(item.get("role", "user"))
        content = str(item.get("content", ""))
        if content:
            messages.append(cast(ChatCompletionMessageParam, {"role": role, "content": content}))
    messages.append({"role": "user", "content": prompt})
    client = get_async_openai_client()
    response = await client.chat.completions.create(
        model=settings.openai_chat_model,
        messages=messages,
        temperature=0,
        max_tokens=settings.llm_max_tokens,
        timeout=settings.llm_timeout_seconds,
    )
    if not response.choices:
        return ""
    return response.choices[0].message.content or ""


async def get_lightrag() -> LightRAG:
    """Return the process-wide LightRAG instance, initializing storages once.

    Returns:
        A ready-to-query/insert ``LightRAG`` backed by PG stores.
    """
    global _rag
    if _rag is not None:
        return _rag

    settings = get_settings()
    os.makedirs(settings.lightrag_working_dir, exist_ok=True)
    _configure_postgres_env()
    rag = LightRAG(
        working_dir=settings.lightrag_working_dir,
        workspace=settings.rag_pg_workspace,
        kv_storage="PGKVStorage",
        vector_storage="PGVectorStorage",
        graph_storage="PGGraphStorage",
        doc_status_storage="PGDocStatusStorage",
        embedding_func=_embed,
        llm_model_func=_llm,
    )
    await rag.initialize_storages()
    await initialize_pipeline_status()
    _rag = rag
    return _rag


async def lightrag_ready() -> bool:
    """Return True when the LightRAG Postgres accepts connections.

    Returns:
        ``True`` on a successful ``SELECT 1``, else ``False``.
    """
    settings = get_settings()
    try:
        conn = await asyncpg.connect(dsn=settings.rag_db_url, timeout=5)
        try:
            await conn.execute("SELECT 1")
        finally:
            await conn.close()
        return True
    except Exception:
        return False


async def aquery_context(
    question: str,
    *,
    mode: Literal["local", "hybrid"],
) -> str:
    """Run a LightRAG context-only query.

    Args:
        question: Natural-language user question.
        mode: LightRAG query mode (``local`` or ``hybrid``).

    Returns:
        Retrieved context string (possibly empty).
    """
    settings = get_settings()
    rag = await get_lightrag()
    result = await rag.aquery(
        question,
        param=QueryParam(
            mode=mode,
            only_need_context=True,
            top_k=settings.retrieval_top_k,
        ),
    )
    if result is None:
        return ""
    return str(result).strip()
