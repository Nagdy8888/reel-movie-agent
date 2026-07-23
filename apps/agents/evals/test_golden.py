"""Live behavioral evaluation for the grounded Reel agent."""

import json
import re
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import HumanMessage

from agents.graph import build_graph
from agents.prompts.system import EMPTY_CONTEXT_REPLY
from agents.settings import get_settings, validate_runtime_settings

pytestmark = pytest.mark.agent_eval
_DATASET_PATH = Path(__file__).with_name("golden_questions.json")
_MOVIE_CITATION = re.compile(r"\[(movie:\d+)\]")


def _cases() -> list[dict[str, Any]]:
    """Load the versioned golden-question cases."""
    payload = json.loads(_DATASET_PATH.read_text(encoding="utf-8"))
    return list(payload["cases"])


@pytest.fixture(scope="session")
def live_graph():
    """Build one validated graph for the cost-gated live evaluation."""
    validate_runtime_settings(get_settings())
    return build_graph()


@pytest.mark.parametrize("case", _cases(), ids=lambda case: str(case["id"]))
def test_golden_behavior(live_graph, case: dict[str, Any]) -> None:
    """Assert routing, sources, citations, quality terms, and fail-closed behavior."""
    result = live_graph.invoke(
        {"messages": [HumanMessage(content=case["question"])]},
        config={
            "run_name": f"golden-{case['id']}",
            "tags": ["agent-eval", "golden-v1"],
            "metadata": {"eval_case": case["id"], "dataset_version": 1},
        },
    )

    answer = str(result["messages"][-1].content)
    sources = result.get("sources", [])
    source_ids = {str(source["id"]) for source in sources}
    citations = set(_MOVIE_CITATION.findall(answer))

    assert result["intent"] == case["expected_intent"]
    assert set(case["expected_source_ids"]) <= source_ids
    assert len(source_ids) >= case["minimum_sources"]

    if case["expect_fail_closed"]:
        assert answer == EMPTY_CONTEXT_REPLY
        assert not citations
        return

    assert answer != EMPTY_CONTEXT_REPLY
    assert len(citations) >= case["minimum_citations"]
    assert citations <= source_ids
    if "maximum_citations" in case:
        assert len(citations) <= case["maximum_citations"]
    answer_lower = answer.casefold()
    for term in case["required_terms"]:
        assert term.casefold() in answer_lower
    for term in case["forbidden_terms"]:
        assert term.casefold() not in answer_lower
