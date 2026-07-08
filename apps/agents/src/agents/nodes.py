"""Nodes for the GraphRAG Reel agent."""

from langchain_core.messages import AIMessage, SystemMessage

from agents.clients import get_chat_model
from agents.prompts.system import (
    EMPTY_CONTEXT_REPLY,
    GENERATE_SYSTEM_V1,
    ROUTER_SYSTEM_V1,
)
from agents.state import AgentState, GenerateUpdate, RouterUpdate
from agents.tools import TOOLS


def router(state: AgentState) -> RouterUpdate:
    """Force a retrieval tool call for the question (never answers directly).

    Reads from state:  messages
    Writes to state:   messages (an AI message that only carries tool calls)
    Side effects:      one OpenAI call (tools bound, tool_choice forced)
    Failure mode:      RetryPolicy retries; otherwise run fails cleanly.
    """
    # tool_choice="any" forces the model to emit a tool call and NOT free-form
    # prose, so ungrounded model knowledge can never be streamed to the user.
    # Safe from infinite loops because retrieval is a single hop (tools ->
    # generate), so the router runs only once per turn.
    model = get_chat_model().bind_tools(TOOLS, tool_choice="any")
    system = SystemMessage(content=ROUTER_SYSTEM_V1)
    reply = model.invoke([system, *state["messages"]])
    # Belt-and-suspenders: drop any content the model may still attach.
    reply.content = ""
    return {"messages": [reply]}


def generate(state: AgentState) -> GenerateUpdate:
    """Produce the final grounded answer with citations (fail-closed).

    Reads from state:  messages (including ToolMessages with retrieved context)
    Writes to state:   messages (final AI answer)
    Side effects:      one OpenAI call when retrieval context is present
    Failure mode:      if no context was retrieved, answers "I don't know"
                       rather than fabricating (no LLM call).
    """
    context = "\n\n".join(
        str(message.content) for message in state["messages"] if message.type == "tool"
    )
    if not context.strip() or context.strip() == "No results.":
        return {"messages": [AIMessage(content=EMPTY_CONTEXT_REPLY)]}

    model = get_chat_model()
    system = SystemMessage(content=GENERATE_SYSTEM_V1.format(context=context))
    reply = model.invoke([system, *state["messages"]])
    return {"messages": [reply]}
