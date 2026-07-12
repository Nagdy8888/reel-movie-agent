"""Full knowledge graph endpoint."""

from fastapi import APIRouter, Depends, Response
from starlette.concurrency import run_in_threadpool

from agents.artifacts import full_graph
from api.auth import current_user
from api.schemas import GraphOut

router = APIRouter(tags=["graph"], dependencies=[Depends(current_user)])


@router.get("/graph", response_model=GraphOut)
async def get_full_graph(response: Response) -> GraphOut:
    """Return the authenticated user's visible movie knowledge graph."""
    response.headers["Cache-Control"] = "no-store"
    graph_data = await run_in_threadpool(full_graph)
    return GraphOut(**graph_data)
