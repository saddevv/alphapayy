from typing import Literal

from pydantic import BaseModel

from .chat import GraphChatResponse


class StreamResultEvent(BaseModel):
    event: Literal["result"]
    data: GraphChatResponse


class StreamDoneEvent(BaseModel):
    event: Literal["done"]


class StreamErrorEvent(BaseModel):
    event: Literal["error"]
    detail: str
    status_code: int | None = None
