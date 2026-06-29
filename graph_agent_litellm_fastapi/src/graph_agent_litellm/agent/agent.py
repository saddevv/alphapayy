import json
from typing import Any

from graph_agent_litellm.agent.state import AgentRunState
from graph_agent_litellm.api_models.chat import ChatResponse
from graph_agent_litellm.core.config import Settings
from graph_agent_litellm.llm.client import LiteLLMClient
from graph_agent_litellm.llm.prompts import FINAL_RESPONSE_INSTRUCTION, GRAPH_AGENT_SYSTEM_PROMPT
from graph_agent_litellm.tools.executor import ToolExecutor, extract_data
from graph_agent_litellm.tools.registry import ToolRegistry


class GraphAgent:
    """Thin custom agent loop.

    The loop is intentionally explicit: call model, execute tool calls, append results, repeat.
    """

    def __init__(
        self,
        *,
        llm_client: LiteLLMClient,
        registry: ToolRegistry,
        executor: ToolExecutor,
        settings: Settings,
    ) -> None:
        self._llm = llm_client
        self._registry = registry
        self._executor = executor
        self._settings = settings

    async def run(self, *, messages: list[dict[str, Any]], thread_id: str | None = None) -> ChatResponse:
        state = AgentRunState(messages=self._initial_messages(messages))
        answer = ""

        for turn in range(self._settings.agent_max_turns):
            state.turn = turn + 1
            response = await self._llm.complete(
                messages=state.messages,
                tools=self._registry.openai_tools(),
                tool_choice="auto",
            )

            if not response.tool_calls:
                answer = response.content
                state.messages.append({"role": "assistant", "content": answer})
                break

            assistant_message = {
                "role": "assistant",
                "content": response.content or "",
                "tool_calls": [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {"name": call.name, "arguments": json.dumps(call.args)},
                    }
                    for call in response.tool_calls
                ],
            }
            state.messages.append(assistant_message)

            records = await self._executor.execute_calls(response.tool_calls)
            state.tool_calls.extend(records)
            state.data = extract_data(state.tool_calls)

            for record in records:
                state.messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": record.id,
                        "name": record.name,
                        "content": json.dumps(
                            {"error": record.error} if record.error else record.result,
                            default=str,
                        ),
                    }
                )
        else:
            answer = await self._finalize(state)

        if not answer.strip() and state.tool_calls:
            answer = await self._finalize(state)

        return ChatResponse(
            thread_id=thread_id,
            answer=answer,
            data=state.data,
            tool_calls=state.tool_calls,
            messages=state.messages,
        )

    def _initial_messages(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        user_messages = [message for message in messages if message.get("role") != "system"]
        system_messages = [message for message in messages if message.get("role") == "system"]
        return [
            {"role": "system", "content": GRAPH_AGENT_SYSTEM_PROMPT},
            *system_messages,
            *user_messages,
        ]

    async def _finalize(self, state: AgentRunState) -> str:
        final_messages = [
            *state.messages,
            {"role": "user", "content": FINAL_RESPONSE_INSTRUCTION},
        ]
        response = await self._llm.complete(messages=final_messages, tools=None, tool_choice=None)
        content = response.content.strip()
        if content:
            state.messages.append({"role": "assistant", "content": content})
        return content

