"""Tests for prompt construction."""

from agents.prompts.system import (
    CONVERSE_SYSTEM_V1,
    GENERATE_SYSTEM_V1,
    GENERATE_SYSTEM_V3,
    ROUTER_SYSTEM_V1,
)


def test_generate_prompt_embeds_context() -> None:
    """The generate prompt includes provided context text."""
    prompt = GENERATE_SYSTEM_V1.format(context="Forrest Gump (1994)")
    assert "Forrest Gump (1994)" in prompt
    assert "ONLY the facts explicitly present in the retrieved context" in prompt


def test_router_prompt_lists_all_intents() -> None:
    """The router prompt names each branch label and embeds the question."""
    prompt = ROUTER_SYSTEM_V1.format(question="hello there")
    assert "hello there" in prompt
    for label in ("factual", "recommend", "chitchat"):
        assert label in prompt


def test_converse_prompt_forbids_asserting_movie_facts() -> None:
    """The chitchat prompt must not let the model invent movie facts."""
    assert "Do NOT state specific movie facts" in CONVERSE_SYSTEM_V1


def test_generate_v3_supports_recommendations_and_context() -> None:
    """V3 embeds context and explicitly allows recommendation answers."""
    prompt = GENERATE_SYSTEM_V3.format(context="Cloud Atlas (2012)")
    assert "Cloud Atlas (2012)" in prompt
    assert "DO recommend" in prompt
