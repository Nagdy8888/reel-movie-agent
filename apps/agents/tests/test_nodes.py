"""Unit tests for GraphRAG generate fail-closed behavior."""

from unittest.mock import MagicMock, patch

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from agents.nodes import generate
from agents.prompts.system import EMPTY_CONTEXT_REPLY


def test_generate_fail_closed_on_empty_context() -> None:
    """Without tool context, generate returns I-don't-know (no LLM call)."""
    state = {"messages": [HumanMessage(content="Who directed Inception?")]}
    with patch("agents.nodes.get_chat_model") as get_model:
        update = generate(state)
        get_model.assert_not_called()
    assert isinstance(update["messages"][0], AIMessage)
    assert update["messages"][0].content == EMPTY_CONTEXT_REPLY


def test_generate_fail_closed_on_no_results() -> None:
    """Tool replies of 'No results.' are treated as empty context."""
    state = {
        "messages": [
            HumanMessage(content="Find a movie about purple elephants"),
            AIMessage(content="", tool_calls=[{"name": "semantic_search", "args": {}, "id": "1"}]),
            ToolMessage(content="No results.", tool_call_id="1"),
        ]
    }
    with patch("agents.nodes.get_chat_model") as get_model:
        update = generate(state)
        get_model.assert_not_called()
    assert update["messages"][0].content == EMPTY_CONTEXT_REPLY


def test_generate_uses_context_when_present() -> None:
    """With retrieval context, generate invokes the chat model."""
    fake_reply = AIMessage(content="Tom Hanks acted in Forrest Gump.")
    fake_model = MagicMock()
    fake_model.invoke.return_value = fake_reply
    state = {
        "messages": [
            HumanMessage(content="What movies did Tom Hanks act in?"),
            AIMessage(content="", tool_calls=[{"name": "graph_query", "args": {}, "id": "1"}]),
            ToolMessage(
                content="{'title': 'Forrest Gump', 'actor': 'Tom Hanks'}",
                tool_call_id="1",
            ),
        ]
    }
    with patch("agents.nodes.get_chat_model", return_value=fake_model):
        update = generate(state)
    fake_model.invoke.assert_called_once()
    assert update["messages"] == [fake_reply]
