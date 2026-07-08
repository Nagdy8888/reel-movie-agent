# Phase 2 — Minimal LangGraph Agent (Studio + LangSmith + Docker)

## Objective

Build the **simplest possible working agent**: a LangGraph graph with one node that sends the conversation to OpenAI and returns a reply. Make it:
1. Visible/runnable in **LangGraph Studio** (`langgraph dev`).
2. **Traced in LangSmith**.
3. **Runnable in Docker** (a `docker-compose.yml` with an `agent` service).

No Neo4j, no retrieval, no FastAPI yet. This proves the LangGraph + OpenAI + LangSmith + Docker toolchain end-to-end.

## Prerequisites

- Phase 1 complete (`uv sync` works, packages import).
- `.env` has `OPENAI_API_KEY`, `LANGSMITH_API_KEY`, `LANGSMITH_TRACING=true`, `LANGSMITH_PROJECT`.

## Steps

### 1. Agent settings — `apps/agents/src/agents/settings.py`

```python
"""Environment-backed configuration for the Reel agent."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentSettings(BaseSettings):
    """Settings for the agent, loaded from environment / .env."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    openai_api_key: str = Field(description="OpenAI API key.")
    openai_chat_model: str = Field(
        default="gpt-4o-mini", description="Chat model used by the agent."
    )
    llm_timeout_seconds: float = Field(
        default=30.0, description="Per-call LLM timeout in seconds."
    )
    llm_max_tokens: int = Field(
        default=1024, description="Maximum tokens per LLM completion."
    )


def get_settings() -> AgentSettings:
    """Return a fresh AgentSettings instance.

    Kept as a function (not a module-level singleton) so importing the graph in
    LangGraph Studio does not fail if env is loaded slightly later.
    """
    return AgentSettings()
```

### 2. Cached client factory — `apps/agents/src/agents/clients.py`

```python
"""Cached, shared client factories for the agent."""

from functools import lru_cache

from langchain_openai import ChatOpenAI

from agents.settings import get_settings


@lru_cache(maxsize=1)
def get_chat_model() -> ChatOpenAI:
    """Return the shared chat model with a timeout and token cap.

    Cached so the client (and its HTTP pool) is created once, not per call.
    """
    settings = get_settings()
    return ChatOpenAI(
        model=settings.openai_chat_model,
        api_key=settings.openai_api_key,
        timeout=settings.llm_timeout_seconds,
        max_tokens=settings.llm_max_tokens,
    )
```

### 3. State — `apps/agents/src/agents/state.py`

```python
"""State schema for the Reel agent graph."""

from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    """Conversation state.

    messages: full chat history. Reducer `add_messages` appends new messages
        instead of overwriting, so each node can return only its new message(s).
    """

    messages: Annotated[list[AnyMessage], add_messages]
```

### 4. Node + graph — `apps/agents/src/agents/nodes.py`

```python
"""Nodes for the minimal Reel agent."""

from langchain_core.messages import AIMessage

from agents.clients import get_chat_model
from agents.state import AgentState


def respond(state: AgentState) -> dict[str, list[AIMessage]]:
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
```

### 5. Compiled graph — `apps/agents/src/agents/graph.py`

```python
"""Assemble and compile the minimal Reel agent graph."""

from langgraph.graph import END, START, StateGraph
from langgraph.pregel import RetryPolicy

from agents.nodes import respond
from agents.state import AgentState


def build_graph() -> "CompiledStateGraph":
    """Build and compile the agent graph.

    A single `respond` node wired START -> respond -> END. Later phases add
    retrieval nodes and a checkpointer.
    """
    builder = StateGraph(AgentState)
    builder.add_node("respond", respond, retry=RetryPolicy(max_attempts=3))
    builder.add_edge(START, "respond")
    builder.add_edge("respond", END)
    return builder.compile()


graph = build_graph()
```

> Note: the import string `agents.graph:graph` must resolve to the compiled `graph` object above. If your editor flags the `CompiledStateGraph` type name, import it under `TYPE_CHECKING` from `langgraph.graph.state` or just annotate the return as the value of `builder.compile()` without the quoted type.

### 6. LangGraph Studio config — `apps/agents/langgraph.json`

```json
{
  "dependencies": ["."],
  "graphs": {
    "agent": "./src/agents/graph.py:graph"
  },
  "env": "../../.env",
  "python_version": "3.11"
}
```

### 7. Run in LangGraph Studio + confirm LangSmith

Install the CLI and run the dev server from `apps/agents`:

```powershell
uv add --dev "langgraph-cli[inmem]"
cd apps/agents
uv run langgraph dev
```

- A browser opens LangGraph Studio pointing at the local server.
- In Studio, select the `agent` graph, send a message (e.g. "Hello, who are you?"), and confirm you get a reply.
- Open LangSmith → project `reel-agent` → confirm a trace for the run appears.

Stop the server with Ctrl+C when done. Return to repo root: `cd ../..`.

### 8. Dockerize the agent dev server

Create `apps/agents/Dockerfile`:

```dockerfile
# syntax=docker/dockerfile:1
FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
# Copy the workspace so uv can resolve the `agents` member.
COPY pyproject.toml uv.lock ./
COPY apps/agents ./apps/agents
COPY apps/backend ./apps/backend
RUN uv sync --frozen --package agents --group dev
WORKDIR /app/apps/agents
EXPOSE 2024
CMD ["uv", "run", "langgraph", "dev", "--host", "0.0.0.0", "--port", "2024", "--no-browser"]
```

Create `docker-compose.yml` at the repo root (this file GROWS in later phases; start with just the agent):

```yaml
services:
  agent:
    build:
      context: .
      dockerfile: apps/agents/Dockerfile
    env_file: [.env]
    ports:
      - "2024:2024"
    volumes:
      - ./apps/agents:/app/apps/agents   # live-reload source
      - ./.env:/app/.env:ro              # so langgraph.json "../../.env" resolves in-container
```

Build and run:

```powershell
docker compose build agent
docker compose up agent
```

Confirm the dev server starts and is reachable at `http://localhost:2024`.

## Environment variables

`OPENAI_API_KEY`, `OPENAI_CHAT_MODEL`, `LANGSMITH_TRACING`, `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT`, `LLM_TIMEOUT_SECONDS`, `LLM_MAX_TOKENS`.

## Acceptance criteria

- [ ] `uv run langgraph dev` (from `apps/agents`) starts and the `agent` graph loads in Studio.
- [ ] Sending a message in Studio returns an OpenAI-generated reply.
- [ ] A matching trace appears in LangSmith project `reel-agent`.
- [ ] `docker compose up agent` starts the dev server on port 2024 without errors.
- [ ] `uv run ruff check .` passes; every new function/module has a docstring.

## Do NOT

- Do NOT add Neo4j, retrieval, tools, or a checkpointer yet (Phases 3–4).
- Do NOT construct `ChatOpenAI` inside the node — use the cached `get_chat_model()`.
- Do NOT hardcode the API key or model — read from settings.

## Relevant rules & skills

- Rules: `langgraph-agent`, `python-standards`, `documentation`, `security` (timeout + max_tokens).
- Skills: `add-agent-node` (pattern for the node), `verify-standards`.
