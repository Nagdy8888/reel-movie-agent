"""Read-only Cypher enforcement for LLM-generated queries."""

import re

_WRITE_CLAUSE = re.compile(
    r"\b(CREATE|MERGE|DELETE|SET|REMOVE|DROP|LOAD\s+CSV|FOREACH|CALL\s*\{)\b",
    re.IGNORECASE,
)


class UnsafeCypherError(ValueError):
    """Raised when generated Cypher contains a write or unsafe clause."""


def ensure_read_only(query: str) -> str:
    """Return the query unchanged if it is read-only, else raise.

    Args:
        query: Candidate Cypher produced by the LLM.

    Returns:
        The validated read-only query.

    Raises:
        UnsafeCypherError: If the query contains any write clause.
    """
    if _WRITE_CLAUSE.search(query):
        raise UnsafeCypherError("Generated Cypher contains a write clause; rejected.")
    return query


def strip_cypher_fences(text: str) -> str:
    """Remove optional markdown code fences around a Cypher statement.

    Args:
        text: Raw LLM output that may wrap Cypher in triple backticks.

    Returns:
        The Cypher string with fences removed.
    """
    cleaned = text.strip()
    if not cleaned.startswith("```"):
        return cleaned
    lines = cleaned.splitlines()
    body = lines[1:]
    if body and body[-1].strip().startswith("```"):
        body = body[:-1]
    return "\n".join(body).strip()
