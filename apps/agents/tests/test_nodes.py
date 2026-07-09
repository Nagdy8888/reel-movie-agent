"""Unit tests for GraphRAG routing, conversation, and generate behavior."""

from unittest.mock import MagicMock, patch

from langchain_core.messages import AIMessage, HumanMessage

from agents.nodes import converse, generate, retrieve, route
from agents.prompts.system import EMPTY_CONTEXT_REPLY


def test_route_classifies_greeting_as_chitchat() -> None:
    """A greeting is routed to the chitchat branch (no retrieval)."""
    fake_llm = MagicMock()
    fake_llm.invoke.return_value = MagicMock(content="chitchat")
    with patch("agents.nodes.get_utility_llm", return_value=fake_llm):
        update = route({"messages": [HumanMessage(content="hello")]})
    assert update["intent"] == "chitchat"


def test_route_classifies_open_request_as_recommend() -> None:
    """An open-ended 'suggest a film' request is routed to recommend."""
    fake_llm = MagicMock()
    fake_llm.invoke.return_value = MagicMock(content="recommend\n")
    with patch("agents.nodes.get_utility_llm", return_value=fake_llm):
        update = route({"messages": [HumanMessage(content="suggest me a film to watch")]})
    assert update["intent"] == "recommend"


def test_route_defaults_to_factual_on_llm_error() -> None:
    """If the classifier errors, routing falls back to grounded factual retrieval."""
    fake_llm = MagicMock()
    fake_llm.invoke.side_effect = RuntimeError("boom")
    with patch("agents.nodes.get_utility_llm", return_value=fake_llm):
        update = route({"messages": [HumanMessage(content="who directed The Matrix?")]})
    assert update["intent"] == "factual"


def test_converse_answers_without_retrieval_context() -> None:
    """Chitchat is answered by the chat model with no graph context needed."""
    fake_reply = AIMessage(content="Hi! I can help you explore movies.")
    fake_model = MagicMock()
    fake_model.invoke.return_value = fake_reply
    with patch("agents.nodes.get_chat_model", return_value=fake_model):
        update = converse({"messages": [HumanMessage(content="hello")]})
    fake_model.invoke.assert_called_once()
    assert update["messages"] == [fake_reply]


def test_retrieve_falls_back_for_empty_recommendation() -> None:
    """An empty recommendation turn falls back to well-reviewed movies."""
    state = {
        "messages": [HumanMessage(content="suggest me a film to watch")],
        "intent": "recommend",
    }
    empty_artifacts = {"sources": [], "graph": {"nodes": [], "links": []}}
    with (
        patch("agents.nodes.run_graph_query", return_value=""),
        patch("agents.nodes.run_semantic_search", return_value=[]),
        patch(
            "agents.nodes.run_recommendation_fallback",
            return_value=["Movie: Cloud Atlas"],
        ) as fallback,
        patch("agents.nodes.run_rerank", side_effect=lambda _q, candidates: candidates),
        patch("agents.nodes.build_retrieval_artifacts", return_value=empty_artifacts),
    ):
        update = retrieve(state)
    fallback.assert_called_once()
    assert "Movie: Cloud Atlas" in update["context"]


def test_retrieve_no_fallback_for_empty_factual() -> None:
    """A factual turn with no matches stays empty (fail-closed), no fallback."""
    state = {
        "messages": [HumanMessage(content="who directed a nonexistent film")],
        "intent": "factual",
    }
    empty_artifacts = {"sources": [], "graph": {"nodes": [], "links": []}}
    with (
        patch("agents.nodes.run_graph_query", return_value=""),
        patch("agents.nodes.run_semantic_search", return_value=[]),
        patch("agents.nodes.run_recommendation_fallback") as fallback,
        patch("agents.nodes.run_rerank", side_effect=lambda _q, candidates: candidates),
        patch("agents.nodes.build_retrieval_artifacts", return_value=empty_artifacts),
    ):
        update = retrieve(state)
    fallback.assert_not_called()
    assert update["context"] == ""


def test_generate_fail_closed_on_empty_context() -> None:
    """Without retrieval context, generate returns I-don't-know (no LLM call)."""
    state = {"messages": [HumanMessage(content="Who directed Inception?")]}
    with patch("agents.nodes.get_chat_model") as get_model:
        update = generate(state)
        get_model.assert_not_called()
    assert isinstance(update["messages"][0], AIMessage)
    assert update["messages"][0].content == EMPTY_CONTEXT_REPLY


def test_generate_fail_closed_on_whitespace_context() -> None:
    """Whitespace-only context is treated as empty and skips the LLM."""
    state = {
        "messages": [HumanMessage(content="Find a movie about purple elephants")],
        "context": "   ",
    }
    with patch("agents.nodes.get_chat_model") as get_model:
        update = generate(state)
        get_model.assert_not_called()
    assert update["messages"][0].content == EMPTY_CONTEXT_REPLY


def test_generate_uses_context_when_present() -> None:
    """With retrieval context in state, generate invokes the chat model."""
    fake_reply = AIMessage(content="Tom Hanks acted in Forrest Gump.")
    fake_model = MagicMock()
    fake_model.invoke.return_value = fake_reply
    state = {
        "messages": [HumanMessage(content="What movies did Tom Hanks act in?")],
        "context": "[Graph facts]\n{'title': 'Forrest Gump', 'actor': 'Tom Hanks'}",
    }
    with patch("agents.nodes.get_chat_model", return_value=fake_model):
        update = generate(state)
    fake_model.invoke.assert_called_once()
    assert update["messages"] == [fake_reply]
