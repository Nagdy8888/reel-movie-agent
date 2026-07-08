"""Nodes for the minimal Reel agent."""

from agents.clients import get_chat_model
from agents.state import AgentState, RespondUpdate


def respond(state: AgentState) -> RespondUpdate:
    """Generate an assistant reply from the conversation so far.

    Reads from state:  messages
    Writes to state:   messages (one new AI reply, appended via add_messages)
    Side effects:      one OpenAI chat completion
    Failure mode:      exception propagates; RetryPolicy on the node retries
                       transient errors, otherwise the run fails cleanly.
    """
    model = get_chat_model()
    reply = model.invoke(state["messages"])
    return {"messages": [reply]}
