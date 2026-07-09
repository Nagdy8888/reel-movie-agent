"""Tests for prompt construction."""

from agents.prompts.system import GENERATE_SYSTEM_V1


def test_generate_prompt_embeds_context() -> None:
    """The generate prompt includes provided context text."""
    prompt = GENERATE_SYSTEM_V1.format(context="Forrest Gump (1994)")
    assert "Forrest Gump (1994)" in prompt
    assert "ONLY the facts explicitly present in the retrieved context" in prompt
