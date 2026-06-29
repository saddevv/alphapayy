from pydantic import BaseModel, Field


class ErrorResponse(BaseModel):
    detail: str = Field(description="Error message")


class HealthResponse(BaseModel):
    status: str = Field(description="Service status", examples=["ok"])
    service: str = Field(description="Service identifier", examples=["graph-agent-standalone"])
