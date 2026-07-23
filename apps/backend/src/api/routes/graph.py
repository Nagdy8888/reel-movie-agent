"""Full knowledge graph endpoint."""

from fastapi import APIRouter, Depends, Request, Response
from starlette.concurrency import run_in_threadpool

from agents.artifacts import full_graph
from api.auth import current_user
from api.limiter import get_authenticated_user_id, limiter
from api.schemas import GraphOut

router = APIRouter(tags=["graph"], dependencies=[Depends(current_user)])


@router.get("/graph", response_model=GraphOut)
@limiter.limit("60/minute")
@limiter.limit("60/minute", key_func=get_authenticated_user_id)
async def get_full_graph(request: Request, response: Response) -> GraphOut:
    """Return the authenticated user's visible movie knowledge graph."""
    del request
    response.headers["Cache-Control"] = "no-store"
    graph_data = await run_in_threadpool(full_graph)
    return GraphOut.model_validate(graph_data)
