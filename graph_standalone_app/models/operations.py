from typing import Any

from pydantic import BaseModel, Field


class ResourceOperationSummary(BaseModel):
    resource: str = Field(description="Resource type")
    operation_count: int = Field(description="Operation count for resource")
    operations: list[str] = Field(description="Operation names")


class OperationsCatalogResponse(BaseModel):
    resource_count: int = Field(description="Total resources with operations")
    total_operations: int = Field(description="Total operations across all resources")
    resources: list[ResourceOperationSummary] = Field(
        description="Operation summaries grouped by resource.",
    )


class ResourceOperationsResponse(BaseModel):
    resource: str = Field(description="Resource type")
    operation_count: int = Field(description="Operation count for resource")
    operations: list[dict[str, Any]] = Field(description="Detailed operation metadata")
