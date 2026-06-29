from fastapi import APIRouter

from graph_agent_litellm.api_models.common import HealthResponse


def create_health_router(service_name: str) -> APIRouter:
    router = APIRouter(tags=["system"])

    @router.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse(status="ok", service=service_name)

    return router

