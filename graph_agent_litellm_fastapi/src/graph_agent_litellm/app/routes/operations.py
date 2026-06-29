from collections.abc import Callable

from fastapi import APIRouter, Depends

from graph_agent_litellm.api_models.operations import OperationsResponse
from graph_agent_litellm.app.dependencies import get_operations_service
from graph_agent_litellm.services.operations_service import OperationsService


def create_operations_router(auth_dependency: Callable) -> APIRouter:
    router = APIRouter(prefix="/v1/graph", tags=["graph"], dependencies=[Depends(auth_dependency)])

    @router.get("/operations", response_model=OperationsResponse)
    async def list_operations(
        service: OperationsService = Depends(get_operations_service),
    ) -> OperationsResponse:
        return service.list_operations()

    return router

