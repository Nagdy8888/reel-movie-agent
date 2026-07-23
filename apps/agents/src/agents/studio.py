"""Validated LangGraph Studio entrypoint for the Reel agent."""

from agents.clients import configure_langsmith
from agents.graph import build_graph
from agents.settings import get_settings, validate_runtime_settings


def build_studio_graph():
    """Validate agent configuration and build the Studio graph.

    Returns:
        A compiled graph without an application-owned checkpointer.
    """
    settings = get_settings()
    validate_runtime_settings(settings)
    configure_langsmith()
    return build_graph()


graph = build_studio_graph()
