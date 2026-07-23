"""Offline contract tests for the live agent evaluation dataset."""

import json
from pathlib import Path


def test_golden_dataset_contract() -> None:
    """Golden cases have unique IDs and cover quality, failure, and injection."""
    path = Path(__file__).parents[1] / "evals" / "golden_questions.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    cases = payload["cases"]
    ids = [case["id"] for case in cases]

    assert payload["version"] == 1
    assert len(cases) >= 6
    assert len(ids) == len(set(ids))
    assert any(case["expect_fail_closed"] for case in cases)
    assert sum("injection" in case["id"] for case in cases) >= 2
    for case in cases:
        assert case["question"].strip()
        assert case["expected_intent"] in {"factual", "recommend", "chitchat"}
        assert case["minimum_sources"] >= 0
        assert case["minimum_citations"] >= 0
        assert all(source_id.startswith("movie:") for source_id in case["expected_source_ids"])
