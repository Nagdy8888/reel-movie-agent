"""Generate short conversation titles for the chat sidebar."""

import re

from agents.clients import get_utility_llm
from api.prompts.conversation_title import CONVERSATION_TITLE_V1

PLACEHOLDER_TITLE = "New chat"
_MAX_TITLE_LEN = 80


def _fallback_title(user_message: str) -> str:
    """Derive a title from the user message when the LLM call fails."""
    text = " ".join(user_message.split())
    if len(text) <= _MAX_TITLE_LEN:
        return text
    return f"{text[: _MAX_TITLE_LEN - 3].rstrip()}..."


def _sanitize_title(raw: str) -> str:
    """Normalize model output into a single-line sidebar title."""
    title = raw.strip().strip("\"'").splitlines()[0].strip()
    title = re.sub(r"\s+", " ", title)
    title = title.rstrip(".")
    if len(title) > _MAX_TITLE_LEN:
        title = f"{title[: _MAX_TITLE_LEN - 3].rstrip()}..."
    return title


def generate_conversation_title(user_message: str, assistant_preview: str = "") -> str:
    """Return a short LLM-generated title for a new conversation.

    Args:
        user_message: The user's first message in the thread.
        assistant_preview: Optional start of the assistant reply for context.

    Returns:
        A concise sidebar title, or a truncated user message on failure.
    """
    assistant_section = ""
    preview = assistant_preview.strip()
    if preview:
        assistant_section = f"\nAssistant reply (excerpt):\n{preview[:400]}\n"

    prompt = CONVERSATION_TITLE_V1.format(
        user_message=user_message.strip(),
        assistant_section=assistant_section,
    )
    try:
        raw = str(get_utility_llm().invoke(prompt).content)
        title = _sanitize_title(raw)
        return title or _fallback_title(user_message)
    except (OSError, ValueError, TypeError):
        return _fallback_title(user_message)
