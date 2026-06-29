from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


MessageRole = Literal["system", "user", "assistant", "tool"]


class ChatMessageIn(BaseModel):
    model_config = ConfigDict(extra="allow")

    role: MessageRole | str = Field(default="user")
    content: str = Field(default="")
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    tool_call_id: str | None = None
    name: str | None = None


class ChatInput(BaseModel):
    model_config = ConfigDict(extra="allow")

    messages: list[ChatMessageIn] = Field(default_factory=list)
    thread_id: str | None = None
    user_id: str | None = None


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    input: ChatInput | None = None
    messages: list[ChatMessageIn] | None = None
    thread_id: str | None = None
    user_id: str | None = None

    def normalized_input(self) -> ChatInput:
        if self.input is not None:
            return self.input
        return ChatInput(
            messages=self.messages or [],
            thread_id=self.thread_id,
            user_id=self.user_id,
        )


class ToolCallRecord(BaseModel):
    id: str
    name: str
    args: dict[str, Any] = Field(default_factory=dict)
    result: Any = None
    error: str | None = None
    read_only: bool = True


class ChatResponse(BaseModel):
    thread_id: str | None = None
    answer: str = ""
    data: list[Any] = Field(default_factory=list)
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    messages: list[dict[str, Any]] = Field(default_factory=list)


class StreamResultEvent(BaseModel):
    event: Literal["result"]
    data: ChatResponse


class StreamDoneEvent(BaseModel):
    event: Literal["done"]


class StreamErrorEvent(BaseModel):
    event: Literal["error"]
    detail: str
    code: str | None = None

