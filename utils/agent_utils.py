"""Utilities shared across agents."""
import json
import logging
from enum import Enum
from typing import Annotated, Any, List, Literal, Optional, Sequence, TypedDict

import pandas as pd
from langchain_core.messages import ToolMessage
from langchain_core.runnables import RunnableLambda, RunnableWithFallbacks
from langgraph.graph.message import AnyMessage, add_messages
from langgraph.prebuilt import ToolNode
from pydantic.v1 import BaseModel, Field, validator

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tool call argument / name extraction (provider-agnostic)
# ---------------------------------------------------------------------------

def get_tool_call_args(tool_call: Any) -> dict:
    """Return arguments for a tool call, coping with different provider payloads."""
    if tool_call is None:
        return {}

    if isinstance(tool_call, dict):
        args = tool_call.get("args")
        if isinstance(args, dict):
            return args
        if isinstance(args, str):
            try:
                return json.loads(args)
            except json.JSONDecodeError:
                return {}

        function_payload = tool_call.get("function")
        if isinstance(function_payload, dict):
            arguments = function_payload.get("arguments")
            if isinstance(arguments, dict):
                return arguments
            if isinstance(arguments, str):
                try:
                    return json.loads(arguments)
                except json.JSONDecodeError:
                    return {}

    for attr in ("args", "arguments"):
        if hasattr(tool_call, attr):
            value = getattr(tool_call, attr)
            if isinstance(value, dict):
                return value
            if isinstance(value, str):
                try:
                    return json.loads(value)
                except json.JSONDecodeError:
                    return {}

    function_payload = getattr(tool_call, "function", None)
    if function_payload is not None:
        arguments = getattr(function_payload, "arguments", None)
        if isinstance(arguments, dict):
            return arguments
        if isinstance(arguments, str):
            try:
                return json.loads(arguments)
            except json.JSONDecodeError:
                return {}

    return {}


def get_tool_call_name(tool_call: Any) -> str | None:
    """Return the tool/function name regardless of provider schema."""
    if tool_call is None:
        return None

    if isinstance(tool_call, dict):
        if "name" in tool_call and isinstance(tool_call["name"], str):
            return tool_call["name"].strip()
        function_payload = tool_call.get("function")
        if isinstance(function_payload, dict):
            name = function_payload.get("name")
            if isinstance(name, str):
                return name.strip()
        return None

    name = getattr(tool_call, "name", None)
    if isinstance(name, str):
        return name.strip()

    function_payload = getattr(tool_call, "function", None)
    if function_payload is not None:
        name = getattr(function_payload, "name", None)
        if isinstance(name, str):
            return name.strip()

    return None


# ---------------------------------------------------------------------------
# Agent enum
# ---------------------------------------------------------------------------

class Agents(Enum):
    SentinelAgent = "SentinelAgent"
    OpenSearchAgent = "OpenSearchAgent"
    WazuhAgent = "WazuhAgent"
    MISPAgent = "MISPAgent"
    RAGAgent = "RAGAgent"
    GeneralTalk = "GeneralTalk"
    CorrelationAgent = "CorrelationAgent"
    GraphAgent = "GraphAgent"


# ---------------------------------------------------------------------------
# Typed output containers
# ---------------------------------------------------------------------------

class AgentsInput(TypedDict):
    agent: Agents
    question: str
    add_visualization: bool


class DFOutput(TypedDict):
    agent: Agents
    df: Any


class QueryOutput(TypedDict):
    agent: Agents
    query_statement: Any


class ChartOutput(TypedDict):
    agent: Agents
    plotly_json: Any
    answer: str


# ---------------------------------------------------------------------------
# State reducer helpers
# ---------------------------------------------------------------------------

def list_merger(list1: list | None, list2: list | None) -> list:
    """Merge two lists of dicts, keyed by the 'agent' field.

    If the same agent appears in both, update the existing entry.
    """
    list1 = list1 or []
    list2 = list2 or []

    try:
        merged: dict[Any, Any] = {item["agent"]: item for item in list1}
        for new_item in list2:
            agent = new_item.get("agent")
            if agent in merged:
                merged[agent].update(new_item)
            else:
                merged[agent] = new_item
        return list(merged.values())
    except KeyError as exc:
        raise KeyError(f"Key 'agent' missing in list_merger input: {exc}") from exc


def list_updater(list1: list | None, list2: list | None) -> list:
    """Append new entries to the existing sequence, preserving order."""
    return list(list1 or []) + list(list2 or [])


def replace_with_latest(current: Any, new: Any) -> Any:
    """Replace the stored value when a new update is provided."""
    if new is None:
        return current if current is not None else []
    return new


def latest_scalar(current: Any, new: Any) -> Any:
    """Keep the previous scalar unless a new value is provided."""
    return current if new is None else new


# ---------------------------------------------------------------------------
# Graph agent state
# ---------------------------------------------------------------------------

class State(TypedDict):
    # Shared cross-agent channels (kept for backward-compat with multi-agent stack)
    query_statement: Annotated[Sequence[QueryOutput], list_merger]
    df: Annotated[Sequence[DFOutput], list_merger]
    plotly_json: Annotated[Sequence[ChartOutput], list_merger]
    correlated_data: Annotated[List[dict], replace_with_latest]
    messages: Annotated[Sequence[AnyMessage], add_messages]

    # Per-agent message channels
    sentinel_messages: Annotated[Sequence[AnyMessage], add_messages]
    opensearch_messages: Annotated[Sequence[AnyMessage], add_messages]
    wazuh_messages: Annotated[Sequence[AnyMessage], add_messages]
    misp_messages: Annotated[Sequence[AnyMessage], add_messages]
    rag_messages: Annotated[Sequence[AnyMessage], add_messages]
    correlation_messages: Annotated[Sequence[AnyMessage], add_messages]

    # Graph agent-specific channel
    graph_messages: Annotated[Sequence[AnyMessage], add_messages]

    next: Annotated[Sequence[AgentsInput], list_updater]
    actor: str

    # Codemode execution state
    codemode_turn: Annotated[int, latest_scalar]
    codemode_requires_schema: Annotated[bool, latest_scalar]
    codemode_stop_after_success: Annotated[bool, latest_scalar]
    codemode_eval_status: Annotated[str, latest_scalar]
    codemode_route_reason: Annotated[str, latest_scalar]
    codemode_eval_reason: Annotated[str, latest_scalar]


class ChartState(TypedDict):
    query_statement: Annotated[Sequence[QueryOutput], list_merger]
    df: Annotated[Sequence[DFOutput], list_merger]
    plotly_json: Annotated[Sequence[ChartOutput], list_merger]
    messages: Annotated[Sequence[AnyMessage], add_messages]
    sentinel_messages: Annotated[Sequence[AnyMessage], add_messages]
    opensearch_messages: Annotated[Sequence[AnyMessage], add_messages]
    wazuh_messages: Annotated[Sequence[AnyMessage], add_messages]
    misp_messages: Annotated[Sequence[AnyMessage], add_messages]
    rag_messages: Annotated[Sequence[AnyMessage], add_messages]
    chart_type: str


# ---------------------------------------------------------------------------
# Tool node helpers
# ---------------------------------------------------------------------------

def create_tool_node_with_fallback(tools: list, message_key: str) -> RunnableWithFallbacks[Any, dict]:
    """Create a ToolNode with a fallback to handle errors and surface them to the agent."""
    return ToolNode(tools, messages_key=message_key).with_fallbacks(
        [RunnableLambda(handle_tool_error)], exception_key="error"
    )


def handle_tool_error(state: dict) -> dict:
    """Return a ToolMessage error for every pending tool call in graph_messages."""
    error = state.get("error")

    # The Graph agent stores its messages under 'graph_messages'.
    # Fall back to 'messages' for other agents in the multi-agent stack.
    last_message = None
    for key in ("graph_messages", "messages"):
        msgs = state.get(key)
        if msgs:
            last_message = msgs[-1]
            break

    if last_message is None or not getattr(last_message, "tool_calls", None):
        logger.warning("handle_tool_error: no tool calls found in state")
        return {}

    error_messages = [
        ToolMessage(
            content=f"Error: {repr(error)}\nPlease fix your tool call and try again.",
            tool_call_id=tc["id"],
        )
        for tc in last_message.tool_calls
    ]

    # Determine which channel the messages came from and write back to the same key
    if state.get("graph_messages"):
        return {"graph_messages": error_messages}
    return {"messages": error_messages}
