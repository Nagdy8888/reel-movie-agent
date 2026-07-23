"""FastAPI dependency providers."""

from typing import Annotated

from fastapi import Depends, Request
from langgraph.graph.state import CompiledStateGraph

from api.auth import User, current_user
from api.services.chats import ChatStore
from api.settings import BackendSettings, get_settings

SettingsDep = Annotated[BackendSettings, Depends(get_settings)]
UserDep = Annotated[User, Depends(current_user)]


def get_graph(request: Request) -> CompiledStateGraph:
    """Return the compiled agent graph built during lifespan."""
    return request.app.state.graph


def get_chat_store(request: Request) -> ChatStore:
    """Return a chat store bound to the app's Postgres pool."""
    return ChatStore(request.app.state.db_pool)


GraphDep = Annotated[CompiledStateGraph, Depends(get_graph)]
ChatStoreDep = Annotated[ChatStore, Depends(get_chat_store)]
