from graph_agent_litellm.api_models.operations import OperationSummary, OperationsResponse
from graph_agent_litellm.tools.registry import ToolRegistry


class OperationsService:
    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    def list_operations(self) -> OperationsResponse:
        operations = [
            OperationSummary(
                name=tool.name,
                description=tool.description,
                read_only=tool.read_only,
                requires_confirmation=tool.requires_confirmation,
                args_schema=tool.args_model.model_json_schema(),
            )
            for tool in self._registry.list()
        ]
        return OperationsResponse(operation_count=len(operations), operations=operations)

