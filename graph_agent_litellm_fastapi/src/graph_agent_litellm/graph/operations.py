from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class GraphOperation:
    name: str
    method: str
    endpoint: str
    description: str
    read_only: bool = True
    required_params: tuple[str, ...] = ()
    optional_params: tuple[str, ...] = ()
    body_required: bool = False
    api_version: str = "v1.0"


@dataclass
class GraphOperationCatalog:
    """Small operation catalog used by generic Graph tools.

    This is intentionally data-first. Adding coverage should mean adding entries here or loading
    them from a JSON/YAML catalog, not changing the agent loop.
    """

    operations: dict[str, GraphOperation] = field(default_factory=dict)

    @classmethod
    def default(cls) -> "GraphOperationCatalog":
        catalog = cls()
        for operation in _DEFAULT_OPERATIONS:
            catalog.operations[operation.name] = operation
        return catalog

    def get(self, name: str) -> GraphOperation | None:
        return self.operations.get(name)

    def list(self) -> list[GraphOperation]:
        return sorted(self.operations.values(), key=lambda item: item.name)

    def to_dicts(self) -> list[dict[str, Any]]:
        return [
            {
                "name": op.name,
                "method": op.method,
                "endpoint": op.endpoint,
                "description": op.description,
                "read_only": op.read_only,
                "required_params": list(op.required_params),
                "optional_params": list(op.optional_params),
                "body_required": op.body_required,
                "api_version": op.api_version,
            }
            for op in self.list()
        ]


_DEFAULT_OPERATIONS = [
    GraphOperation("list_users", "GET", "/users", "List directory users.", optional_params=("$select", "$filter", "$top")),
    GraphOperation("get_user", "GET", "/users/{user_id}", "Get a user by ID or UPN.", optional_params=("$select",)),
    GraphOperation("search_user", "GET", "/users", "Find users by display name, mail, or UPN.", optional_params=("$filter", "$top")),
    GraphOperation("update_user", "PATCH", "/users/{user_id}", "Update user properties.", read_only=False, body_required=True),
    GraphOperation("delete_user", "DELETE", "/users/{user_id}", "Delete a user.", read_only=False),
    GraphOperation("revoke_user_sessions", "POST", "/users/{user_id}/revokeSignInSessions", "Revoke user sign-in sessions.", read_only=False),
    GraphOperation("list_groups", "GET", "/groups", "List groups.", optional_params=("$select", "$filter", "$top")),
    GraphOperation("get_group", "GET", "/groups/{group_id}", "Get a group by ID."),
    GraphOperation("list_group_members", "GET", "/groups/{group_id}/members", "List group members.", optional_params=("$select", "$top")),
    GraphOperation("add_group_member", "POST", "/groups/{group_id}/members/$ref", "Add a member to a group.", read_only=False, body_required=True),
    GraphOperation("remove_group_member", "DELETE", "/groups/{group_id}/members/{member_id}/$ref", "Remove a member from a group.", read_only=False),
    GraphOperation("list_devices", "GET", "/devices", "List directory devices.", optional_params=("$select", "$filter", "$top")),
    GraphOperation("list_sign_in_logs", "GET", "/auditLogs/signIns", "List Entra sign-in logs.", optional_params=("$filter", "$top"), api_version="beta"),
    GraphOperation("list_directory_audits", "GET", "/auditLogs/directoryAudits", "List directory audit events.", optional_params=("$filter", "$top"), api_version="beta"),
    GraphOperation("list_security_alerts", "GET", "/security/alerts_v2", "List Microsoft Graph security alerts.", optional_params=("$filter", "$top", "$count")),
    GraphOperation("list_security_incidents", "GET", "/security/incidents", "List Microsoft Graph security incidents.", optional_params=("$filter", "$top")),
]
