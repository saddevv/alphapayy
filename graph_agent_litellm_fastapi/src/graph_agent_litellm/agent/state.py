from typing import Any

from pydantic import BaseModel, Field

from graph_agent_litellm.api_models.chat import ToolCallRecord


class AgentRunState(BaseModel):
    messages: list[dict[str, Any]]
    turn: int = 0
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    data: list[Any] = Field(default_factory=list)

