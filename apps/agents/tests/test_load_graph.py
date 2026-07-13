"""Tests for the batched Neo4j movie graph loader."""

from __future__ import annotations

import pytest

from ingestion.load_graph import _assert_manifest, batched, read_bundle


def test_packaged_bundle_contains_exactly_five_thousand_movies() -> None:
    """The generated package asset should satisfy the selected movie count."""
    bundle = read_bundle()

    assert len(bundle["movies"]) == 5_000
    assert bundle["manifest"]["nodeCounts"]["Movie"] == 5_000
    assert bundle["manifest"]["limits"]["withinAuraFree"] is True


def test_batched_preserves_order_and_validates_size() -> None:
    """Batch splitting should be deterministic and reject invalid sizes."""
    rows = [{"tmdbId": item} for item in range(5)]

    assert list(batched(rows, 2)) == [
        [{"tmdbId": 0}, {"tmdbId": 1}],
        [{"tmdbId": 2}, {"tmdbId": 3}],
        [{"tmdbId": 4}],
    ]
    with pytest.raises(ValueError, match="positive"):
        list(batched(rows, 0))


def test_assert_manifest_reports_count_differences() -> None:
    """Manifest verification should expose expected and actual counts."""
    manifest = {
        "nodeCounts": {"Movie": 2},
        "relationshipCounts": {"ACTED_IN": 3},
    }

    with pytest.raises(RuntimeError, match="ACTED_IN"):
        _assert_manifest({"Movie": 2, "ACTED_IN": 2}, manifest)
