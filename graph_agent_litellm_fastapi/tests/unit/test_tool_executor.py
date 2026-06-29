from typing import Any

import pytest
from pydantic import BaseModel

from graph_agent_litellm.core.config import Settings
from graph_agent_litellm.llm.types import LLMToolCall
from graph_agent_litellm.tools.base import ConfirmableArgs, ToolDefinition
from graph_agent_litellm.tools.executor import ToolExecutor
from graph_agent_litellm.tools.registry import ToolRegistry


class EchoArgs(BaseModel):
    value: str


class MutateArgs(ConfirmableArgs):
    value: str


async def echo(args: EchoArgs) -> dict[str, Any]:
    return {"value": args.value}


async def mutate(args: MutateArgs) -> dict[str, Any]:
    return {"mutated": args.value}


def build_executor() -> ToolExecutor:
    registry = ToolRegistry()
    registry.register(ToolDefinition("echo", "Echo input.", EchoArgs, echo))
    registry.register(
        ToolDefinition(
            "mutate",
            "Mutate something.",
            MutateArgs,
            mutate,
            read_only=False,
            requires_confirmation=True,
        )
    )
    return ToolExecutor(registry, Settings())


@pytest.mark.asyncio
async def test_executes_valid_read_tool() -> None:
    executor = build_executor()
    records = await executor.execute_calls([LLMToolCall(id="1", name="echo", args={"value": "ok"})])

    assert records[0].error is None
    assert records[0].result == {"value": "ok"}


@pytest.mark.asyncio
async def test_blocks_unconfirmed_mutation() -> None:
    executor = build_executor()
    records = await executor.execute_calls([LLMToolCall(id="1", name="mutate", args={"value": "x"})])

    assert records[0].result is None
    assert "requires confirmed=true" in records[0].error


@pytest.mark.asyncio
async def test_allows_confirmed_mutation() -> None:
    executor = build_executor()
    records = await executor.execute_calls(
        [LLMToolCall(id="1", name="mutate", args={"value": "x", "confirmed": True})]
    )

    assert records[0].error is None
    assert records[0].result == {"mutated": "x"}

