import asyncio
import logging
import os
import uuid
from typing import Any

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.security import APIKeyHeader
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage

from graph_agent.agent import graph_graph
from graph_agent.operations_registry import list_all_resources, list_resource_operations

from .models import (
    ErrorResponse,
    GraphChatRequest,
    GraphChatResponse,
    GraphMessageOut,
    HealthResponse,
    OperationsCatalogResponse,
    ResourceOperationSummary,
    ResourceOperationsResponse,
    StreamDoneEvent,
    StreamErrorEvent,
    StreamResultEvent,
)

logger = logging.getLogger(__name__)

load_dotenv()


app = FastAPI(
    title="Microsoft Graph Agent (Standalone)",
    version="0.1.0",
    description=(
        "Standalone Microsoft Graph AI agent API. Supports operation discovery, "
        "synchronous chat execution, and SSE streaming responses."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

LLM_API_KEY = os.getenv("LLM_API_KEY")
API_KEY_NAME = os.getenv("API_KEY_NAME", "x-api-key")
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)


def verify_api_key(api_key: str = Security(api_key_header)) -> bool:
    """Validate API key when LLM_API_KEY is configured."""
    if not LLM_API_KEY:
        return True

    if api_key is None:
        raise HTTPException(
            status_code=401,
            detail="API key is missing",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    if api_key != LLM_API_KEY:
        raise HTTPException(
            status_code=403,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    return True


def _safe_string(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _to_lc_message(message: dict[str, Any]) -> BaseMessage:
    role = (message.get("role") or message.get("type") or "user").strip().lower()
    content = _safe_string(message.get("content", ""))

    if role in {"user", "human"}:
        return HumanMessage(content=content)

    if role in {"assistant", "ai"}:
        tool_calls = message.get("tool_calls") or []
        return AIMessage(content=content, tool_calls=tool_calls)

    if role == "system":
        return SystemMessage(content=content)

    if role == "tool":
        tool_call_id = _safe_string(message.get("tool_call_id") or f"tool_{uuid.uuid4().hex[:8]}")
        return ToolMessage(
            content=content,
            tool_call_id=tool_call_id,
            name=message.get("name"),
        )

    return HumanMessage(content=content)


def _normalize_messages(raw_messages: list[dict[str, Any]]) -> list[BaseMessage]:
    messages: list[BaseMessage] = []
    for item in raw_messages or []:
        if not isinstance(item, dict):
            continue
        messages.append(_to_lc_message(item))
    return messages


def _extract_final_answer(messages: list[Any]) -> str:
    for message in reversed(messages or []):
        if isinstance(message, AIMessage) and _safe_string(message.content).strip():
            return _safe_string(message.content)
        if isinstance(message, dict):
            if message.get("type") in {"ai", "assistant"} and _safe_string(message.get("content")).strip():
                return _safe_string(message.get("content"))
    return ""


def _extract_latest_query(query_statement: list[Any] | None) -> str | None:
    for item in reversed(query_statement or []):
        if isinstance(item, dict):
            statement = item.get("query_statement")
            if statement is not None:
                return _safe_string(statement)
    return None


def _extract_latest_df(df_records: list[Any] | None) -> list[Any]:
    for item in reversed(df_records or []):
        if isinstance(item, dict) and "df" in item:
            value = item.get("df")
            if isinstance(value, list):
                return value
            return []
    return []


def _run_graph_agent(raw_messages: list[dict[str, Any]], thread_id: str | None = None) -> GraphChatResponse:
    graph_messages = _normalize_messages(raw_messages)
    if not graph_messages:
        raise HTTPException(status_code=400, detail="At least one message is required.")

    config = None
    if thread_id:
        config = {"configurable": {"thread_id": thread_id}}

    logger.info("Running graph agent", extra={"thread_id": thread_id, "message_count": len(graph_messages)})
    result = graph_graph.invoke({"graph_messages": graph_messages}, config=config)

    final_graph_messages = result.get("graph_messages", [])
    answer = _extract_final_answer(final_graph_messages)
    latest_query = _extract_latest_query(result.get("query_statement"))
    latest_df = _extract_latest_df(result.get("df"))

    response_messages = [
        GraphMessageOut(
            type=getattr(msg, "type", "unknown") if not isinstance(msg, dict) else msg.get("type", "unknown"),
            content=_safe_string(getattr(msg, "content", "")) if not isinstance(msg, dict) else _safe_string(msg.get("content", "")),
            tool_calls=getattr(msg, "tool_calls", []) if not isinstance(msg, dict) else (msg.get("tool_calls") or []),
        )
        for msg in final_graph_messages
    ]

    return GraphChatResponse(
        thread_id=thread_id,
        answer=answer,
        query_statement=latest_query,
        df=latest_df,
        graph_messages=response_messages,
    )


@app.get(
    "/health",
    response_model=HealthResponse,
    tags=["system"],
    summary="Health Check",
    description="Returns basic liveness information for the standalone Graph service.",
)
def health() -> HealthResponse:
    return HealthResponse(status="ok", service="graph-agent-standalone")


@app.get(
    "/graph/operations",
    response_model=OperationsCatalogResponse,
    tags=["graph"],
    summary="List Graph Operation Coverage",
    description="Returns all supported Microsoft Graph resource families and operation names.",
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
)
def graph_operations(_authenticated: bool = Depends(verify_api_key)) -> OperationsCatalogResponse:
    resources = list_all_resources()
    payload: list[ResourceOperationSummary] = []
    total_operations = 0

    for resource in resources:
        operations = list_resource_operations(resource)
        count = len(operations)
        total_operations += count
        payload.append(
            ResourceOperationSummary(
                resource=resource,
                operation_count=count,
                operations=[op.get("name") for op in operations],
            )
        )

    return OperationsCatalogResponse(
        resource_count=len(resources),
        total_operations=total_operations,
        resources=payload,
    )


@app.get(
    "/graph/operations/{resource_type}",
    response_model=ResourceOperationsResponse,
    tags=["graph"],
    summary="List Operations By Resource",
    description="Returns detailed operation metadata for a specific Graph resource family.",
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def graph_resource_operations(
    resource_type: str,
    _authenticated: bool = Depends(verify_api_key),
) -> ResourceOperationsResponse:
    operations = list_resource_operations(resource_type)
    if not operations:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No operations found for resource '{resource_type}'. "
                "Check /graph/operations for supported resources."
            ),
        )

    return ResourceOperationsResponse(
        resource=resource_type,
        operation_count=len(operations),
        operations=operations,
    )


@app.post(
    "/graph/chat",
    response_model=GraphChatResponse,
    tags=["graph"],
    summary="Execute Graph Chat",
    description=(
        "Runs the Graph agent on provided conversation messages. Supports both direct payload "
        "format and LangServe-like `input` wrapper format."
    ),
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
)
async def chat(
    payload: GraphChatRequest,
    _authenticated: bool = Depends(verify_api_key),
) -> GraphChatResponse:
    normalized = payload.normalized_input()
    messages = [item.model_dump(exclude_none=True) for item in normalized.messages]
    thread_id = normalized.thread_id or normalized.user_id
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _run_graph_agent, messages, thread_id)


@app.post(
    "/graph/chat/stream",
    tags=["graph"],
    summary="Execute Graph Chat (SSE)",
    description="Runs the Graph agent and streams result/error events as `text/event-stream`.",
    responses={
        200: {
            "description": "Server-Sent Events stream with result/done/error events.",
            "content": {
                "text/event-stream": {
                    "examples": {
                        "result": {
                            "summary": "Result event",
                            "value": "data: {\"event\":\"result\",\"data\":{...}}\\n\\n",
                        },
                        "done": {
                            "summary": "Done event",
                            "value": "data: {\"event\":\"done\"}\\n\\n",
                        },
                        "error": {
                            "summary": "Error event",
                            "value": "data: {\"event\":\"error\",\"detail\":\"...\"}\\n\\n",
                        },
                    }
                }
            },
        },
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
    },
)
async def chat_stream(
    payload: GraphChatRequest,
    _authenticated: bool = Depends(verify_api_key),
) -> StreamingResponse:
    normalized = payload.normalized_input()
    messages = [item.model_dump(exclude_none=True) for item in normalized.messages]
    thread_id = normalized.thread_id or normalized.user_id

    async def event_stream():
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(None, _run_graph_agent, messages, thread_id)
            result_event = StreamResultEvent(event="result", data=response)
            done_event = StreamDoneEvent(event="done")
            # SSE requires actual newlines as delimiters, not escaped sequences
            yield f"data: {result_event.model_dump_json()}\n\n"
            yield f"data: {done_event.model_dump_json()}\n\n"
        except HTTPException as http_error:
            body = StreamErrorEvent(
                event="error",
                status_code=http_error.status_code,
                detail=str(http_error.detail),
            )
            yield f"data: {body.model_dump_json()}\n\n"
        except Exception as error:
            logger.exception("Unexpected error in SSE stream")
            body = StreamErrorEvent(event="error", detail=str(error))
            yield f"data: {body.model_dump_json()}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
