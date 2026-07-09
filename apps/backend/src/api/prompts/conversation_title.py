"""Prompt templates for backend utility LLM calls."""

CONVERSATION_TITLE_V1 = """\
You name movie-discovery chats for a sidebar. Given the user's opening question \
(and optionally the start of the assistant reply), write a concise title.

Rules:
- 3–6 words when possible, never more than 8
- Title case or sentence case is fine
- No quotes, no trailing period, no emojis
- Capture the topic (film, director, genre, comparison, etc.)

User question:
{user_message}
{assistant_section}
Reply with ONLY the title."""
