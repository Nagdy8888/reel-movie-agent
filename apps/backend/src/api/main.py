"""FastAPI application factory and lifespan for the Reel backend."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from agents.graph import build_graph
from agents.memory import build_checkpointer, build_store
from api.routes import chat, health


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Build the graph with memory eagerly and stash it on app.state.

    Fails fast if Neo4j/Postgres/OpenAI config is missing.

    Side effects: creates Postgres checkpointer/store tables if absent.
    """
    checkpointer = build_checkpointer()
    store = build_store()
    app.state.graph = build_graph(checkpointer=checkpointer, store=store)
    app.state.checkpointer = checkpointer
    yield


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(title="Reel API", version="0.1.0", lifespan=lifespan)
    app.include_router(health.router)
    app.include_router(chat.router)
    return app


app = create_app()
