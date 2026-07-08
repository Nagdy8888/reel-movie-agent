---
name: add-agent-node
description: Add a new node to the LangGraph agent in apps/agents following project standards (contract docstring, TypedDict state update, RetryPolicy, versioned prompt, test, Studio check). Use when adding or modifying a LangGraph node, tool, or graph edge.
disable-model-invocation: true
---

# Add an Agent Node

Add a LangGraph node the right way: typed state contract, resilient, traceable, tested.

## Workflow

```
- [ ] 1. Write the node function with a contract docstring
- [ ] 2. Define its TypedDict state update (+ reducer if it accumulates)
- [ ] 3. Register with RetryPolicy and wire edges in graph.py
- [ ] 4. Add a versioned prompt file if it calls the LLM
- [ ] 5. Add a unit/fixture test
- [ ] 6. Confirm it renders in `langgraph dev` Studio
- [ ] 7. Run verify-standards
```

### 1. Node function (`apps/agents/src/agents/nodes.py`)

Contract docstring is mandatory:

```python
def retrieve(state: AgentState) -> RetrieveUpdate:
    """Fetch graph context for the question.

    Reads from state:  messages
    Writes to state:   context
    Side effects:      read-only Neo4j query
    Failure mode:      returns {"context": []} and appends an error label
    """
```

Fail closed: on error, return a safe state — never fabricate an answer from empty context.

### 2. State update (`apps/agents/src/agents/state.py`)

Return a narrow `TypedDict`, not a bare `dict`. Accumulating fields use a documented reducer, e.g. `errors: Annotated[list[str], operator.add]`.

### 3. Wire into the graph (`apps/agents/src/agents/graph.py`)

Register with a `RetryPolicy` and add edges:

```python
builder.add_node("retrieve", retrieve, retry=RetryPolicy(max_attempts=3))
builder.add_edge("router", "retrieve")
```

Keep the graph compiled with the `PostgresSaver` checkpointer + `PostgresStore`.

### 4. Prompt (if LLM-calling)

Put the prompt in a versioned file under `apps/agents/src/agents/prompts/` — no inline strings. Pass `timeout` and `max_tokens`. Tag the run (`run_name`/`tags`/`metadata`) for LangSmith.

### 5. Test (`apps/agents/tests/`)

Use a fake LLM + mocked Neo4j and a checkpointer stub. Assert the state update and the fail-closed path. Each test has a docstring.

### 6. Studio check

Run `langgraph dev` from `apps/agents/` and confirm the node/edges appear and the graph compiles.

### 7. Verify

Run the `verify-standards` skill and fix anything flagged.
