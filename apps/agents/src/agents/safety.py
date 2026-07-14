"""Read-only Cypher enforcement for LLM-generated queries."""

import re

_WRITE_CLAUSE = re.compile(
    r"\b(CREATE|MERGE|DELETE|SET|REMOVE|DROP|LOAD\s+CSV|FOREACH|CALL\s*\{)\b",
    re.IGNORECASE,
)

# String literals, backtick-quoted identifiers, and comments are stripped before
# the write-clause scan so a legitimate read query is not rejected just because a
# movie title or property name contains a keyword (e.g. `WHERE m.title = 'Set It
# Off'` or the film "The Drop"). Whichever construct starts first at a given
# position wins, so quotes inside comments (and vice versa) are handled correctly.
_LITERAL_OR_COMMENT = re.compile(
    r"""
    '(?:\\.|[^'\\])*'      # single-quoted string
    | "(?:\\.|[^"\\])*"    # double-quoted string
    | `(?:``|[^`])*`       # backtick-quoted identifier
    | //[^\n]*             # line comment
    | /\*.*?\*/            # block comment
    """,
    re.VERBOSE | re.DOTALL,
)


class UnsafeCypherError(ValueError):
    """Raised when generated Cypher contains a write or unsafe clause."""


def _strip_literals_and_comments(query: str) -> str:
    """Replace string literals, quoted identifiers, and comments with spaces.

    Args:
        query: Candidate Cypher produced by the LLM.

    Returns:
        The query with literal/comment spans blanked out, so a write-clause
        scan only inspects executable Cypher tokens. Spaces preserve token
        boundaries; an unterminated literal is left intact so the scan stays
        fail-closed.
    """
    return _LITERAL_OR_COMMENT.sub(" ", query)


def ensure_read_only(query: str) -> str:
    """Return the query unchanged if it is read-only, else raise.

    The write-clause scan ignores string literals and comments so a read query
    that merely mentions a write keyword inside a movie title or property value
    is not falsely rejected.

    Args:
        query: Candidate Cypher produced by the LLM.

    Returns:
        The validated read-only query.

    Raises:
        UnsafeCypherError: If the query contains any write clause.
    """
    if _WRITE_CLAUSE.search(_strip_literals_and_comments(query)):
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
