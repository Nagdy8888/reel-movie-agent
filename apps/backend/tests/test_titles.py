"""Tests for LLM-generated conversation titles."""

from unittest.mock import MagicMock, patch

from api.services.titles import (
    PLACEHOLDER_TITLE,
    _fallback_title,
    generate_conversation_title,
)


def test_placeholder_title_constant() -> None:
    """Placeholder title is used for new threads before summarization."""
    assert PLACEHOLDER_TITLE == "New chat"


def test_fallback_title_truncates_long_messages() -> None:
    """Fallback title truncates very long user messages."""
    long_msg = "x" * 100
    title = _fallback_title(long_msg)
    assert len(title) <= 80
    assert title.endswith("...")


@patch("api.services.titles.get_utility_llm")
def test_generate_conversation_title_uses_llm(mock_get_llm: MagicMock) -> None:
    """Title generation returns sanitized LLM output."""
    mock_get_llm.return_value.invoke.return_value.content = '"Tom Hanks Filmography"'
    title = generate_conversation_title("What movies did Tom Hanks act in?")
    assert title == "Tom Hanks Filmography"


@patch("api.services.titles.get_utility_llm")
def test_generate_conversation_title_falls_back_on_error(mock_get_llm: MagicMock) -> None:
    """Title generation falls back to the user message when the LLM fails."""
    mock_get_llm.return_value.invoke.side_effect = OSError("network")
    msg = "Sci-fi like Blade Runner"
    assert generate_conversation_title(msg) == msg
