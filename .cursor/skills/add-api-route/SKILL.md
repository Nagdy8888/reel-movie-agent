---
name: add-api-route
description: Add a new FastAPI endpoint to apps/backend following project standards (Pydantic schemas, dependency injection, response_model, auth, rate limit, docstring, contract test). Use when adding or modifying a backend HTTP route or endpoint.
disable-model-invocation: true
---

# Add an API Route

Add a backend endpoint the right way: thin handler, injected deps, typed I/O, tested.

## Workflow

```
- [ ] 1. Define request/response models in schemas.py
- [ ] 2. Add provider(s) in deps.py
- [ ] 3. Write the thin handler in routes/
- [ ] 4. Register the router
- [ ] 5. Add a route contract test
- [ ] 6. Run verify-standards
```

### 1. Schemas (`apps/backend/src/api/schemas.py`)

Define Pydantic request/response models. Every field has `Field(description=...)`. These become the OpenAPI contract.

### 2. Dependencies (`apps/backend/src/api/deps.py`)

Add any `Depends` providers the route needs (settings, graph, current user, service objects). Never import services lazily inside the handler.

### 3. Handler (`apps/backend/src/api/routes/<area>.py`)

Keep it thin — validate input, call an injected service, shape the response. Requirements:

- `response_model=` set from a `schemas.py` model.
- Auth dependency (router-level `dependencies=[Depends(current_user)]`, unless intentionally public).
- Rate limit expensive/LLM routes.
- A docstring (mandatory).

```python
@router.post("/chat", response_model=ChatResponse)
async def chat(
    body: ChatRequest,
    user: Annotated[User, Depends(current_user)],
    graph: Annotated[CompiledGraph, Depends(get_graph)],
) -> ChatResponse:
    """Answer the user's movie question via the agent graph."""
    return await chat_service.answer(body, user, graph)
```

### 4. Register

Include the router in `main.py` (or its aggregator). Confirm prefix/tags.

### 5. Test (`apps/backend/tests/`)

Contract test with `httpx.AsyncClient`, stubbing deps via `app.dependency_overrides` (mock the graph — no live OpenAI/Neo4j). Cover auth failure and the happy path. Each test has a docstring.

### 6. Verify

Run the `verify-standards` skill (ruff incl. `D`, ruff format, pyright, pytest). Fix anything it flags.
