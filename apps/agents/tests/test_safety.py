"""Unit tests for the read-only Cypher safety validator."""

import pytest

from agents.safety import UnsafeCypherError, ensure_read_only, strip_cypher_fences


def test_ensure_read_only_allows_match() -> None:
    """A plain MATCH query passes through unchanged."""
    query = "MATCH (m:Movie) RETURN m.title LIMIT 5"
    assert ensure_read_only(query) == query


def test_ensure_read_only_rejects_create() -> None:
    """CREATE is rejected as an unsafe write clause."""
    with pytest.raises(UnsafeCypherError):
        ensure_read_only("CREATE (m:Movie {title: 'Hack'})")


def test_ensure_read_only_rejects_delete() -> None:
    """DELETE is rejected as an unsafe write clause."""
    with pytest.raises(UnsafeCypherError):
        ensure_read_only("MATCH (m:Movie) DELETE m")


def test_ensure_read_only_rejects_merge_and_set() -> None:
    """MERGE and SET are rejected as unsafe write clauses."""
    with pytest.raises(UnsafeCypherError):
        ensure_read_only("MERGE (p:Person {name: 'x'}) SET p.born = 1970")


def test_ensure_read_only_rejects_call_subquery() -> None:
    """CALL { } subqueries that can write are rejected."""
    with pytest.raises(UnsafeCypherError):
        ensure_read_only("CALL { CREATE (n:Hack) } RETURN 1")


def test_ensure_read_only_allows_write_keyword_in_string_literal() -> None:
    """A movie title containing a write keyword is not falsely rejected."""
    for title in ("Set It Off", "The Drop", "Creed", "Get Out"):
        query = f"MATCH (m:Movie {{title: '{title}'}}) RETURN m.tmdbId, m.title"
        assert ensure_read_only(query) == query


def test_ensure_read_only_allows_write_keyword_in_comment() -> None:
    """A write keyword inside a comment does not trip the guard."""
    query = "MATCH (m:Movie) RETURN m.title // TODO: never DELETE here"
    assert ensure_read_only(query) == query


def test_ensure_read_only_still_rejects_write_outside_literal() -> None:
    """A real write clause next to a benign string literal is still rejected."""
    with pytest.raises(UnsafeCypherError):
        ensure_read_only("MATCH (m:Movie {title: 'Set It Off'}) SET m.rating = 10")


def test_strip_cypher_fences_removes_markdown() -> None:
    """Markdown fences around Cypher are stripped before validation."""
    fenced = "```cypher\nMATCH (m:Movie) RETURN m.title\n```"
    assert strip_cypher_fences(fenced) == "MATCH (m:Movie) RETURN m.title"
