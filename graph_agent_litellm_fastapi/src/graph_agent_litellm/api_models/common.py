from pydantic import BaseModel, Field


class ErrorResponse(BaseModel):
    detail: str = Field(description="Human-readable error message")
    code: str | None = Field(default=None, description="Stable error code")


class HealthResponse(BaseModel):
    status: str = Field(examples=["ok"])
    service: str

