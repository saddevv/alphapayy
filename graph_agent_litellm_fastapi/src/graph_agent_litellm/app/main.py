from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from graph_agent_litellm.agent.agent import GraphAgent
from graph_agent_litellm.app.routes.chat import create_chat_router
from graph_agent_litellm.app.routes.health import create_health_router
from graph_agent_litellm.app.routes.operations import create_operations_router
from graph_agent_litellm.core.config import Settings, get_settings
from graph_agent_litellm.core.errors import AppError
from graph_agent_litellm.core.logging import configure_logging
from graph_agent_litellm.core.security import build_api_key_dependency
from graph_agent_litellm.graph.auth import GraphTokenProvider
from graph_agent_litellm.graph.client import GraphClient
from graph_agent_litellm.graph.operations import GraphOperationCatalog
from graph_agent_litellm.llm.client import LiteLLMClient
from graph_agent_litellm.services.chat_service import ChatService
from graph_agent_litellm.services.operations_service import OperationsService
from graph_agent_litellm.tools.executor import ToolExecutor
from graph_agent_litellm.tools.graph_tools import GraphToolFactory


def create_app(settings: Settings | None = None) -> FastAPI:
    configure_logging()
    settings = settings or get_settings()

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="Model-agnostic Microsoft Graph agent powered by FastAPI and LiteLLM.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    catalog = GraphOperationCatalog.default()
    token_provider = GraphTokenProvider(settings)
    graph_client = GraphClient(settings, token_provider)
    registry = GraphToolFactory(graph_client, catalog).build_registry()
    executor = ToolExecutor(registry, settings)
    llm_client = LiteLLMClient(settings)
    agent = GraphAgent(
        llm_client=llm_client,
        registry=registry,
        executor=executor,
        settings=settings,
    )

    app.state.settings = settings
    app.state.graph_operation_catalog = catalog
    app.state.tool_registry = registry
    app.state.chat_service = ChatService(agent)
    app.state.operations_service = OperationsService(registry)

    auth_dependency = build_api_key_dependency(settings)
    app.include_router(create_health_router(settings.app_name))
    app.include_router(create_operations_router(auth_dependency))
    app.include_router(create_chat_router(auth_dependency))

    @app.exception_handler(AppError)
    async def app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.message, "code": exc.code, "details": exc.details},
        )

    @app.exception_handler(HTTPException)
    async def http_error_handler(_request: Request, exc: HTTPException) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    return app


app = create_app()

