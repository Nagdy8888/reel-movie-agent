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
    """An empty recommendation turn falls back to top box-office movies."""
    state = {
        "messages": [HumanMessage(content="suggest me a film to watch")],
        "intent": "recommend",
    }
    fallback_artifacts = {
        "sources": [
            {
                "id": "movie:1",
                "title": "Cloud Atlas",
                "subtitle": None,
                "year": "2012",
                "poster_url": None,
                "tags": [],
            }
        ],
        "graph": {"nodes": [], "links": []},
    }
    with (
        patch("agents.nodes.run_graph_query", return_value=""),
        patch("agents.nodes.run_semantic_search", return_value=[]),
        patch(
            "agents.nodes.run_recommendation_fallback",
            return_value=["Movie: Cloud Atlas (2012) [movie:1]"],
        ) as fallback,
        patch("agents.nodes.run_rerank", side_effect=lambda _q, candidates: candidates),
        patch("agents.nodes.build_retrieval_artifacts", return_value=fallback_artifacts),
    ):
        update = retrieve(state)
    fallback.assert_called_once()
    assert "movie:1" in update["context"]


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


def test_retrieve_fails_closed_when_context_has_no_projection_movie() -> None:
    """Unmappable LightRAG context is discarded before answer generation."""
    state = {
        "messages": [HumanMessage(content="tell me about a theme")],
        "intent": "factual",
    }
    empty_artifacts = {"sources": [], "graph": {"nodes": [], "links": []}}
    with (
        patch("agents.nodes.run_graph_query", return_value="entity-only context"),
        patch("agents.nodes.run_semantic_search", return_value=[]),
        patch("agents.nodes.run_rerank", side_effect=lambda _q, candidates: candidates),
        patch("agents.nodes.build_retrieval_artifacts", return_value=empty_artifacts),
    ):
        update = retrieve(state)
    assert update["context"] == ""
    assert "no projection movie recovered" in update["errors"][-1]


def test_retrieve_injects_projection_grounding_for_recovered_movies() -> None:
    """Recovered movies get typed cast/genre facts prepended for generate."""
    state = {
        "messages": [HumanMessage(content="Who starred in The Hunger Games?")],
        "intent": "factual",
    }
    artifacts = {
        "sources": [
            {
                "id": "movie:31186339",
                "title": "The Hunger Games",
                "subtitle": None,
                "year": "2012",
                "poster_url": None,
                "tags": [],
            }
        ],
        "graph": {"nodes": [], "links": []},
    }
    with (
        patch("agents.nodes.run_graph_query", return_value="Katniss Everdeen entity"),
        patch("agents.nodes.run_semantic_search", return_value=[]),
        patch("agents.nodes.run_rerank", side_effect=lambda _q, candidates: candidates),
        patch("agents.nodes.build_retrieval_artifacts", return_value=artifacts),
        patch(
            "agents.nodes.run_projection_grounding",
            return_value=[
                "Movie: The Hunger Games (2012) [movie:31186339]\n"
                "Cast: Jennifer Lawrence as Katniss Everdeen"
            ],
        ) as grounding,
    ):
        update = retrieve(state)
    grounding.assert_called_once_with(["movie:31186339"])
    assert update["context"].startswith("[Projection facts]")
    assert "Jennifer Lawrence as Katniss Everdeen" in update["context"]
    assert "Katniss Everdeen entity" in update["context"]


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
