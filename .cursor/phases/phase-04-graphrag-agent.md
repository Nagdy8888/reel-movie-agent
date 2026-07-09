# Phase 4 — GraphRAG Agent (Read-only Cypher + Vector Tools + Memory)

> **Architecture update (implemented):** the agent evolved from a single-tool
> LLM **router** into a **deterministic hybrid** pipeline. Every turn a single
> `retrieve` node runs **both** retrievers, then merges and reranks the results;
> a single `generate` node answers. Concretely:
> - Flow is `START -> retrieve -> generate -> END` (no router / `ToolNode`).
> - Text2Cypher is hardened: **DB-introspected schema** (`get_graph_schema`,
>   never drifts), **few-shot examples**, and a **bounded self-correction loop**.
> - Semantic search is **hybrid** (vector + full-text/BM25) via
>   `HybridCypherRetriever`, then graph-expanded.
> - An **LLM reranker** (non-streaming utility LLM) trims merged candidates
>   before generation; only the `generate` node streams tokens.
> - Embeddings are **composed from graph facts** (title + tagline + cast + roles
>   + directors + writers), not just the tagline.
>
> The actual source under `apps/agents/src/agents/` is the source of truth. The
> code blocks below reflect the original router design and are kept for history.

## Objective

Upgrade the minimal agent into a real **GraphRAG agent**:
- A **`retrieve` node** that runs both retrievers every turn, then merges + reranks.
- A **robust read-only Text2Cypher** path (introspected schema + few-shot + self-correction) protected by a Cypher-safety validator.
- A **hybrid semantic retriever** (vector + full-text) over composed embeddings, graph-expanded.
- A **fail-closed generate node** that answers with citations, never fabricating from empty context.
- **Memory**: a Postgres checkpointer + store (Supabase Postgres), `thread_id` per conversation.
- Versioned prompts, `RetryPolicy` per node, LangSmith tags/metadata.

At the end, in LangGraph Studio you can ask "What movies did Tom Hanks act in?" (structured/Cypher path) and "a movie about dreams within dreams" (semantic path) and get grounded answers — both retrievers run and the answer is reranked and grounded.

## Prerequisites

- Phase 3 complete: Neo4j loaded + vector index exists.
- `.env` has `SUPABASE_DB_URL` (a Postgres connection string) for the checkpointer/store.

## Steps

### 1. Cypher-safety validator (pure function, testable) — `apps/agents/src/agents/safety.py`

```python
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
```

### 2. Versioned prompts — `apps/agents/src/agents/prompts/`

Create `apps/agents/src/agents/prompts/__init__.py`:
```python
"""Versioned prompt templates for the agent."""
```

Create `apps/agents/src/agents/prompts/system.py`:
```python
"""System + generation prompts (versioned)."""

ROUTER_SYSTEM_V1 = (
    "You are Reel, a movie knowledge assistant. You answer using ONLY the "
    "provided tools to look up facts in a movie knowledge graph. "
    "Use `graph_query` for precise/structured questions (actors, directors, "
    "years, counts). Use `semantic_search` for fuzzy/plot/theme questions. "
    "Call a tool before answering. If tools return nothing, say you don't know."
)

GENERATE_SYSTEM_V1 = (
    "Answer the user's movie question using ONLY the retrieved context below. "
    "If the context is empty or insufficient, say you don't have enough "
    "information — never invent titles, dates, or people. Cite the movie "
    "titles you used.\n\nContext:\n{context}"
)
```

### 3. Retrieval tools — `apps/agents/src/agents/tools.py`

```python
"""Retrieval tools bound to the agent (read-only)."""

from langchain_core.tools import tool
from neo4j_graphrag.embeddings import OpenAIEmbeddings
from neo4j_graphrag.retrievers import Text2CypherRetriever, VectorRetriever

from agents.clients import get_neo4j_driver
from agents.safety import ensure_read_only
from agents.settings import get_settings

NEO4J_SCHEMA = (
    "Node labels: Movie(title, released, tagline), Person(name, born). "
    "Relationships: (Person)-[:ACTED_IN]->(Movie), (Person)-[:DIRECTED]->(Movie)."
)


@tool
def graph_query(question: str) -> str:
    """Answer a structured movie question via read-only Text2Cypher.

    Use for precise facts: who acted in / directed a movie, release years,
    counts. Generated Cypher is validated read-only before execution.
    """
    settings = get_settings()
    driver = get_neo4j_driver()
    from neo4j_graphrag.llm import OpenAILLM

    retriever = Text2CypherRetriever(
        driver=driver,
        llm=OpenAILLM(model_name=settings.openai_chat_model),
        neo4j_schema=NEO4J_SCHEMA,
    )
    # Guard: validate the generated query is read-only before it runs.
    result = retriever.get_search_results(query_text=question)
    ensure_read_only(result.metadata.get("cypher", ""))
    return "\n".join(str(r) for r in result.records) or "No results."


@tool
def semantic_search(question: str) -> str:
    """Answer a fuzzy/plot/theme movie question via vector search.

    Use for questions about what a movie is *about* rather than exact facts.
    """
    settings = get_settings()
    driver = get_neo4j_driver()
    embedder = OpenAIEmbeddings(model=settings.openai_embed_model)
    retriever = VectorRetriever(
        driver,
        index_name=settings.vector_index_name,
        embedder=embedder,
        return_properties=["title", "tagline"],
    )
    result = retriever.search(query_text=question, top_k=5)
    return "\n".join(str(item.content) for item in result.items) or "No results."


TOOLS = [graph_query, semantic_search]
```

> Important on the read-only guard: `Text2CypherRetriever` executes internally, so the primary defense is the **read-only DB user** where available (Phase 3, layer 2) plus the `ensure_read_only` check. If your `neo4j-graphrag` version does not expose the generated Cypher via `result.metadata["cypher"]`, instead generate the Cypher explicitly (LLM prompt → `ensure_read_only` → `session.execute_read`) and drop `Text2CypherRetriever`. Verify the exact API with Context7/docs before finalizing.

### 4. Router + generate nodes — extend `apps/agents/src/agents/nodes.py`

Replace the single `respond` node with a router (tool-calling) + generate. Keep contract docstrings.

```python
"""Nodes for the GraphRAG Reel agent."""

from langchain_core.messages import AIMessage, SystemMessage

from agents.clients import get_chat_model
from agents.prompts.system import GENERATE_SYSTEM_V1, ROUTER_SYSTEM_V1
from agents.state import AgentState
from agents.tools import TOOLS


def router(state: AgentState) -> dict:
    """Decide whether to call a retrieval tool or answer.

    Reads from state:  messages
    Writes to state:   messages (an AI message, possibly with tool calls)
    Side effects:      one OpenAI call (tools bound)
    Failure mode:      RetryPolicy retries; otherwise run fails cleanly.
    """
    model = get_chat_model().bind_tools(TOOLS)
    system = SystemMessage(content=ROUTER_SYSTEM_V1)
    reply = model.invoke([system, *state["messages"]])
    return {"messages": [reply]}


def generate(state: AgentState) -> dict:
    """Produce the final grounded answer with citations (fail-closed).

    Reads from state:  messages (including ToolMessages with retrieved context)
    Writes to state:   messages (final AI answer)
    Side effects:      one OpenAI call
    Failure mode:      if no context was retrieved, answers "I don't know"
                       rather than fabricating.
    """
    context = "\n\n".join(
        str(m.content) for m in state["messages"] if m.type == "tool"
    )
    model = get_chat_model()
    system = SystemMessage(content=GENERATE_SYSTEM_V1.format(context=context or "(none)"))
    reply = model.invoke([system, *state["messages"]])
    return {"messages": [reply]}
```

### 5. Graph wiring + memory — rewrite `apps/agents/src/agents/graph.py`

```python
"""Assemble and compile the GraphRAG Reel agent graph with memory."""

from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.pregel import RetryPolicy

from agents.nodes import generate, router
from agents.state import AgentState
from agents.tools import TOOLS


def build_graph():
    """Build and compile the GraphRAG agent.

    Flow: START -> router -> (tools -> router)* -> generate -> END.
    Compiled WITHOUT a checkpointer here so LangGraph Studio can supply its own;
    the backend (Phase 5) compiles with a Postgres checkpointer + store.
    """
    builder = StateGraph(AgentState)
    builder.add_node("router", router, retry=RetryPolicy(max_attempts=3))
    builder.add_node("tools", ToolNode(TOOLS))
    builder.add_node("generate", generate, retry=RetryPolicy(max_attempts=3))

    builder.add_edge(START, "router")
    builder.add_conditional_edges("router", tools_condition, {"tools": "tools", END: "generate"})
    builder.add_edge("tools", "router")
    builder.add_edge("generate", END)
    return builder.compile()


graph = build_graph()
```

### 6. Checkpointer + store factory — `apps/agents/src/agents/memory.py`

```python
"""Postgres-backed checkpointer and store for agent memory."""

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.store.postgres import PostgresStore

from agents.settings import get_settings


def build_checkpointer() -> PostgresSaver:
    """Create and set up a Postgres checkpointer (Supabase Postgres).

    Side effects: runs `.setup()` (creates checkpoint tables if absent).
    """
    settings = get_settings()
    saver = PostgresSaver.from_conn_string(settings.supabase_db_url)
    saver.setup()
    return saver


def build_store() -> PostgresStore:
    """Create and set up a Postgres cross-conversation store.

    Side effects: runs `.setup()` (creates store tables if absent).
    """
    settings = get_settings()
    store = PostgresStore.from_conn_string(settings.supabase_db_url)
    store.setup()
    return store
```

Add `supabase_db_url: str = Field(description="Postgres URL for checkpointer/store.")` to `AgentSettings`.

> The compiled `graph` in `graph.py` stays checkpointer-less for Studio. The backend will build a checkpointer/store and pass them at compile time (Phase 5 shows the exact call). Optionally expose `build_graph(checkpointer=None, store=None)` so both callers share one builder.

**Supabase connection + verification via the MCP plugin.** The runtime uses the direct Postgres URL in `SUPABASE_DB_URL`, but use the Supabase MCP (project `Reel`, `project_id: "bkhmqtcxoxtrydumgwfd"`) to set up and verify the memory tables — do not use the dashboard. See `.cursor/rules/supabase-mcp.mdc`.

- Confirm the target project and empty state: `list_projects` → pick `Reel`; `list_tables` (project_id `bkhmqtcxoxtrydumgwfd`).
- LangGraph's `.setup()` creates the checkpointer/store tables on first run. After running the backend once (Phase 5), verify with `list_tables` that the `checkpoints*` and store tables exist.
- Run `get_advisors` (type `security`) afterward; the LangGraph tables live in a private schema and should not be exposed via PostgREST/RLS — address any finding.
- `SUPABASE_DB_URL` format: `postgresql://postgres:<db-password>@db.bkhmqtcxoxtrydumgwfd.supabase.co:5432/postgres` (or the pooler URI). The DB password is set by the user in `.env`; the MCP does not return it.

### 7. LangSmith tags/metadata

When invoking the graph (in the backend, Phase 5), pass a `RunnableConfig` with `run_name="reel-chat"`, `tags=["graphrag"]`, and `metadata={"user_id": ..., "thread_id": ...}`. In Studio, runs are tagged automatically.

### 8. Verify in Studio

```powershell
cd apps/agents
uv run langgraph dev
```

Ask both a structured and a semantic question; confirm the router calls the right tool and the answer cites titles. Confirm traces in LangSmith show tool calls.

## Environment variables

Adds `SUPABASE_DB_URL`. Plus all Phase 2/3 vars.

## Acceptance criteria

- [ ] `ensure_read_only` raises on a query containing `CREATE`/`DELETE`/etc. and passes a plain `MATCH`.
- [ ] In Studio, a structured question yields graph facts via robust Text2Cypher (introspected schema + few-shot + self-correction).
- [ ] A semantic question yields hybrid (vector + full-text) matches, graph-expanded into cast/crew/reviews.
- [ ] The `retrieve` node runs both retrievers and reranks; the `generate` node is the only text/streaming producer.
- [ ] With empty/failed retrieval, the answer says it doesn't know (fail-closed) — no fabrication.
- [ ] `build_checkpointer()`/`build_store()` connect to Supabase Postgres and `.setup()` succeeds.
- [ ] `uv run ruff check .` passes; every node has a contract docstring.

## Do NOT

- Do NOT execute LLM-generated Cypher without `ensure_read_only` + a read path (`execute_read`).
- Do NOT inline prompt strings in nodes — import from `prompts/`.
- Do NOT emit an answer from empty context.
- Do NOT construct clients per call — reuse cached factories.

## Relevant rules & skills

- Rules: `langgraph-agent`, `security` (read-only Cypher), `python-standards`, `documentation`.
- Skill: `add-agent-node` (follow its checklist for each node), `verify-standards`.
