import asyncio
from typing import Any

from pydantic import ValidationError

from graph_agent_litellm.api_models.chat import ToolCallRecord
from graph_agent_litellm.core.config import Settings
from graph_agent_litellm.llm.types import LLMToolCall
from graph_agent_litellm.tools.registry import ToolRegistry


class ToolExecutor:
    """Validates and executes model-requested tool calls."""

    def __init__(self, registry: ToolRegistry, settings: Settings) -> None:
        self._registry = registry
        self._settings = settings

    async def execute_calls(self, calls: list[LLMToolCall]) -> list[ToolCallRecord]:
        limited = calls[: self._settings.agent_max_tool_calls]
        if (
            self._settings.agent_parallel_reads
            and len(limited) > 1
            and all(self._is_read_only(call.name) for call in limited)
        ):
            return await asyncio.gather(*(self.execute_call(call) for call in limited))
        records: list[ToolCallRecord] = []
        for call in limited:
            records.append(await self.execute_call(call))
        return records

    async def execute_call(self, call: LLMToolCall) -> ToolCallRecord:
        tool = self._registry.get(call.name)
        if tool is None:
            return ToolCallRecord(
                id=call.id,
                name=call.name,
                args=call.args,
                error=f"Unknown tool '{call.name}'.",
                read_only=False,
            )

        if (
            self._settings.agent_require_mutation_confirmation
            and tool.requires_confirmation
            and not bool(call.args.get("confirmed"))
        ):
            return ToolCallRecord(
                id=call.id,
                name=call.name,
                args=call.args,
                error=(
                    "This operation mutates Microsoft Graph data and requires confirmed=true "
                    "before execution."
                ),
                read_only=tool.read_only,
            )

        try:
            result = await tool.invoke(call.args)
            return ToolCallRecord(
                id=call.id,
                name=call.name,
                args=call.args,
                result=result,
                read_only=tool.read_only,
            )
        except ValidationError as exc:
            return ToolCallRecord(
                id=call.id,
                name=call.name,
                args=call.args,
                error=f"Invalid arguments: {exc.errors()}",
                read_only=tool.read_only,
            )
        except Exception as exc:
            return ToolCallRecord(
                id=call.id,
                name=call.name,
                args=call.args,
                error=str(exc),
                read_only=tool.read_only,
            )

    def _is_read_only(self, name: str) -> bool:
        tool = self._registry.get(name)
        return bool(tool and tool.read_only)


def extract_data(records: list[ToolCallRecord]) -> list[Any]:
    data: list[Any] = []
    for record in records:
        if record.error:
            continue
        payload = record.result
        if isinstance(payload, dict) and isinstance(payload.get("value"), list):
            data.extend(payload["value"])
        elif isinstance(payload, list):
            data.extend(payload)
        elif payload is not None:
            data.append(payload)
    return data

