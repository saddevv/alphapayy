from collections.abc import Callable

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from graph_agent_litellm.api_models.chat import (
    ChatRequest,
    ChatResponse,
    StreamDoneEvent,
    StreamErrorEvent,
    StreamResultEvent,
)
from graph_agent_litellm.app.dependencies import get_chat_service
from graph_agent_litellm.services.chat_service import ChatService


def create_chat_router(auth_dependency: Callable) -> APIRouter:
    router = APIRouter(prefix="/v1/graph", tags=["graph"], dependencies=[Depends(auth_dependency)])

    @router.post("/chat", response_model=ChatResponse)
    async def chat(
        request: ChatRequest,
        service: ChatService = Depends(get_chat_service),
    ) -> ChatResponse:
        return await service.chat(request)

    @router.post("/chat/stream")
    async def chat_stream(
        request: ChatRequest,
        service: ChatService = Depends(get_chat_service),
    ) -> StreamingResponse:
        async def events():
            try:
                response = await service.chat(request)
                yield f"data: {StreamResultEvent(event='result', data=response).model_dump_json()}\n\n"
                yield f"data: {StreamDoneEvent(event='done').model_dump_json()}\n\n"
            except Exception as exc:
                yield f"data: {StreamErrorEvent(event='error', detail=str(exc)).model_dump_json()}\n\n"

        return StreamingResponse(events(), media_type="text/event-stream")

    return router

