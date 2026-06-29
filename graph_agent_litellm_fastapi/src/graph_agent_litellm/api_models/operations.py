from typing import Any

from pydantic import BaseModel, Field


class OperationSummary(BaseModel):
    name: str
    description: str
    read_only: bool
    requires_confirmation: bool
    args_schema: dict[str, Any] = Field(default_factory=dict)


class OperationsResponse(BaseModel):
    operation_count: int
    operations: list[OperationSummary]

