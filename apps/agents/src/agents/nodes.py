"""Nodes for the deterministic hybrid GraphRAG Reel agent."""

from langchain_core.messages import AIMessage, SystemMessage

from agents.clients import get_chat_model
from agents.prompts.system import EMPTY_CONTEXT_REPLY, GENERATE_SYSTEM_V2
from agents.state import AgentState, GenerateUpdate, RetrieveUpdate
from agents.tools import run_graph_query, run_rerank, run_semantic_search


def _latest_question(state: AgentState) -> str:
    """Return the most recent human message text from the conversation.

    Args:
        state: The current agent state.

    Returns:
        The latest human message content, or an empty string if none exists.
    """
    for message in reversed(state["messages"]):
        if message.type == "human":
            return str(message.content)
    return ""


def retrieve(state: AgentState) -> RetrieveUpdate:
    """Run both retrievers, merge, and rerank into grounding context.

    Reads from state:  messages
    Writes to state:   context, errors
    Side effects:      read-only Neo4j queries + non-streaming OpenAI calls
                       (Text2Cypher generation and reranking)
    Failure mode:      returns {"context": "", "errors": [...]} on retrieval
                       failure so `generate` fails closed (never fabricates).
    """
    question = _latest_question(state)
    errors: list[str] = []
    if not question:
        return {"context": "", "errors": ["retrieve: no user question found"]}

    candidates: list[str] = []
    try:
        graph_facts = run_graph_query(question)
        if graph_facts:
            candidates.append(f"[Graph facts]\n{graph_facts}")
    except Exception as exc:
        errors.append(f"graph_query: {exc}")

    try:
        candidates.extend(run_semantic_search(question))
    except Exception as exc:
        errors.append(f"semantic_search: {exc}")

    try:
        candidates = run_rerank(question, candidates)
    except Exception as exc:
        errors.append(f"rerank: {exc}")

    return {"context": "\n\n".join(candidates), "errors": errors}


def generate(state: AgentState) -> GenerateUpdate:
    """Produce the final grounded answer with citations (fail-closed).

    Reads from state:  messages, context
    Writes to state:   messages (final AI answer)
    Side effects:      one streaming OpenAI call when retrieval context exists
    Failure mode:      if no context was retrieved, answers EMPTY_CONTEXT_REPLY
                       rather than fabricating (no LLM call).
    """
    context = state.get("context", "")
    if not context.strip():
        return {"messages": [AIMessage(content=EMPTY_CONTEXT_REPLY)]}

    model = get_chat_model()
    system = SystemMessage(content=GENERATE_SYSTEM_V2.format(context=context))
    reply = model.invoke([system, *state["messages"]])
    return {"messages": [reply]}
