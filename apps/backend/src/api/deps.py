"""FastAPI dependency providers."""

from typing import Annotated

from fastapi import Depends, Request

from api.settings import BackendSettings, get_settings

SettingsDep = Annotated[BackendSettings, Depends(get_settings)]


def get_graph(request: Request):
    """Return the compiled agent graph built during lifespan."""
    return request.app.state.graph


GraphDep = Annotated[object, Depends(get_graph)]
