from typing import Any

from pydantic import BaseModel, Field

from graph_agent_litellm.graph.client import GraphClient
from graph_agent_litellm.graph.operations import GraphOperationCatalog
from graph_agent_litellm.tools.base import ConfirmableArgs, ToolDefinition
from graph_agent_litellm.tools.registry import ToolRegistry


class ListUsersArgs(BaseModel):
    select_fields: list[str] | None = Field(default=None)
    filter_expression: str | None = Field(default=None)
    top: int | None = Field(default=25, ge=1, le=999)


class GetUserArgs(BaseModel):
    user_id: str = Field(description="User object ID or userPrincipalName.")
    select_fields: list[str] | None = None


class SearchUserArgs(BaseModel):
    query: str = Field(description="Display name, mail, or userPrincipalName to search for.")
    top: int = Field(default=5, ge=1, le=25)


class UpdateUserArgs(ConfirmableArgs):
    user_id: str
    update_data: dict[str, Any]


class DeleteUserArgs(ConfirmableArgs):
    user_id: str


class RevokeUserSessionsArgs(ConfirmableArgs):
    user_id: str


class ListGroupsArgs(BaseModel):
    select_fields: list[str] | None = None
    filter_expression: str | None = None
    top: int | None = Field(default=25, ge=1, le=999)


class GetGroupArgs(BaseModel):
    group_id: str


class ListGroupMembersArgs(BaseModel):
    group_id: str
    select_fields: list[str] | None = None
    top: int | None = Field(default=50, ge=1, le=999)


class AddGroupMemberArgs(ConfirmableArgs):
    group_id: str
    member_id: str


class RemoveGroupMemberArgs(ConfirmableArgs):
    group_id: str
    member_id: str


class ListDevicesArgs(BaseModel):
    select_fields: list[str] | None = None
    filter_expression: str | None = None
    top: int | None = Field(default=25, ge=1, le=999)


class LogQueryArgs(BaseModel):
    filter_expression: str | None = None
    top: int | None = Field(default=50, ge=1, le=999)


class SecurityListArgs(BaseModel):
    filter_expression: str | None = None
    top: int | None = Field(default=50, ge=1, le=999)
    count: bool | None = None


class GenericGraphOperationArgs(ConfirmableArgs):
    operation_name: str
    path_params: dict[str, Any] = Field(default_factory=dict)
    body: dict[str, Any] | None = None
    query_params: dict[str, Any] | None = None
    api_version: str | None = None


class GraphToolFactory:
    def __init__(self, client: GraphClient, catalog: GraphOperationCatalog) -> None:
        self._client = client
        self._catalog = catalog

    def build_registry(self) -> ToolRegistry:
        registry = ToolRegistry()
        for tool in [
            ToolDefinition("list_users", "List directory users.", ListUsersArgs, self.list_users),
            ToolDefinition("get_user", "Get a user by object ID or UPN.", GetUserArgs, self.get_user),
            ToolDefinition("search_user", "Search users by display name, mail, or UPN.", SearchUserArgs, self.search_user),
            ToolDefinition("update_user", "Update user properties.", UpdateUserArgs, self.update_user, read_only=False, requires_confirmation=True),
            ToolDefinition("delete_user", "Delete a user.", DeleteUserArgs, self.delete_user, read_only=False, requires_confirmation=True),
            ToolDefinition("revoke_user_sessions", "Revoke all sign-in sessions for a user.", RevokeUserSessionsArgs, self.revoke_user_sessions, read_only=False, requires_confirmation=True),
            ToolDefinition("list_groups", "List Microsoft 365 groups.", ListGroupsArgs, self.list_groups),
            ToolDefinition("get_group", "Get a group by ID.", GetGroupArgs, self.get_group),
            ToolDefinition("list_group_members", "List members of a group.", ListGroupMembersArgs, self.list_group_members),
            ToolDefinition("add_group_member", "Add a directory object to a group.", AddGroupMemberArgs, self.add_group_member, read_only=False, requires_confirmation=True),
            ToolDefinition("remove_group_member", "Remove a directory object from a group.", RemoveGroupMemberArgs, self.remove_group_member, read_only=False, requires_confirmation=True),
            ToolDefinition("list_devices", "List directory devices.", ListDevicesArgs, self.list_devices),
            ToolDefinition("list_sign_in_logs", "List Entra sign-in logs.", LogQueryArgs, self.list_sign_in_logs),
            ToolDefinition("list_directory_audits", "List directory audit events.", LogQueryArgs, self.list_directory_audits),
            ToolDefinition("list_security_alerts", "List Microsoft Graph security alerts.", SecurityListArgs, self.list_security_alerts),
            ToolDefinition("list_security_incidents", "List Microsoft Graph security incidents.", SecurityListArgs, self.list_security_incidents),
            ToolDefinition("graph_operation", "Execute a cataloged Microsoft Graph operation by name.", GenericGraphOperationArgs, self.graph_operation, read_only=False),
        ]:
            registry.register(tool)
        return registry

    async def list_users(self, args: ListUsersArgs) -> Any:
        return await self._client.request("GET", "/users", params=_odata_params(args))

    async def get_user(self, args: GetUserArgs) -> Any:
        return await self._client.request("GET", f"/users/{args.user_id}", params=_select_params(args.select_fields))

    async def search_user(self, args: SearchUserArgs) -> Any:
        escaped = args.query.replace("'", "''")
        filter_expression = (
            f"displayName eq '{escaped}' or userPrincipalName eq '{escaped}' or mail eq '{escaped}'"
        )
        return await self._client.request("GET", "/users", params={"$filter": filter_expression, "$top": args.top})

    async def update_user(self, args: UpdateUserArgs) -> Any:
        return await self._client.request("PATCH", f"/users/{args.user_id}", json_data=args.update_data)

    async def delete_user(self, args: DeleteUserArgs) -> Any:
        return await self._client.request("DELETE", f"/users/{args.user_id}")

    async def revoke_user_sessions(self, args: RevokeUserSessionsArgs) -> Any:
        return await self._client.request("POST", f"/users/{args.user_id}/revokeSignInSessions")

    async def list_groups(self, args: ListGroupsArgs) -> Any:
        return await self._client.request("GET", "/groups", params=_odata_params(args))

    async def get_group(self, args: GetGroupArgs) -> Any:
        return await self._client.request("GET", f"/groups/{args.group_id}")

    async def list_group_members(self, args: ListGroupMembersArgs) -> Any:
        params = _select_params(args.select_fields)
        if args.top:
            params["$top"] = args.top
        return await self._client.request("GET", f"/groups/{args.group_id}/members", params=params)

    async def add_group_member(self, args: AddGroupMemberArgs) -> Any:
        body = {"@odata.id": f"https://graph.microsoft.com/v1.0/directoryObjects/{args.member_id}"}
        return await self._client.request("POST", f"/groups/{args.group_id}/members/$ref", json_data=body)

    async def remove_group_member(self, args: RemoveGroupMemberArgs) -> Any:
        return await self._client.request("DELETE", f"/groups/{args.group_id}/members/{args.member_id}/$ref")

    async def list_devices(self, args: ListDevicesArgs) -> Any:
        return await self._client.request("GET", "/devices", params=_odata_params(args))

    async def list_sign_in_logs(self, args: LogQueryArgs) -> Any:
        return await self._client.request("GET", "/auditLogs/signIns", params=_filter_top_params(args), api_version="beta")

    async def list_directory_audits(self, args: LogQueryArgs) -> Any:
        return await self._client.request("GET", "/auditLogs/directoryAudits", params=_filter_top_params(args), api_version="beta")

    async def list_security_alerts(self, args: SecurityListArgs) -> Any:
        params = _filter_top_params(args)
        if args.count is not None:
            params["$count"] = str(args.count).lower()
        return await self._client.request("GET", "/security/alerts_v2", params=params)

    async def list_security_incidents(self, args: SecurityListArgs) -> Any:
        return await self._client.request("GET", "/security/incidents", params=_filter_top_params(args))

    async def graph_operation(self, args: GenericGraphOperationArgs) -> Any:
        operation = self._catalog.get(args.operation_name)
        if operation is None:
            return {"error": {"message": f"Unknown operation '{args.operation_name}'."}}
        if not operation.read_only and not args.confirmed:
            return {
                "error": {
                    "message": (
                        f"Operation '{args.operation_name}' mutates Microsoft Graph data "
                        "and requires confirmed=true."
                    )
                }
            }
        try:
            endpoint = operation.endpoint.format(**args.path_params)
        except KeyError as exc:
            return {"error": {"message": f"Missing path parameter: {exc.args[0]}."}}
        return await self._client.request(
            operation.method,
            endpoint,
            json_data=args.body,
            params=args.query_params,
            api_version=args.api_version or operation.api_version,
        )


def _select_params(select_fields: list[str] | None) -> dict[str, Any]:
    return {"$select": ",".join(select_fields)} if select_fields else {}


def _odata_params(args: Any) -> dict[str, Any]:
    params = _select_params(getattr(args, "select_fields", None))
    if getattr(args, "filter_expression", None):
        params["$filter"] = args.filter_expression
    if getattr(args, "top", None):
        params["$top"] = args.top
    return params


def _filter_top_params(args: Any) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if getattr(args, "filter_expression", None):
        params["$filter"] = args.filter_expression
    if getattr(args, "top", None):
        params["$top"] = args.top
    return params
