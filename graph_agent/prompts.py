from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from pydantic import BaseModel, Field
from typing import Literal

####################################################################################################
## Resource Selector Prompt

TABLE_SELECTION_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "You are an agent designed to interact with Microsoft Graph API. "
            "When you need to inspect a resource, call get_graph_resource_schema_tool with the full path "
            "(e.g., 'users', 'security/alerts_v2', 'security/identities/healthIssues', 'security/identities/sensors').",
        ),
        MessagesPlaceholder(variable_name="graph_messages"),
    ]
)

####################################################################################################
## Query Generator Prompt

graph_query_system = """You are an expert agent designed to interact with Microsoft Graph API.
Your task is to generate accurate Microsoft Graph API queries and operations based on user questions.

Microsoft Graph API provides access to:
- Azure AD / Entra ID: users, groups, roles, sign-in logs, audit logs, conditional access policies
- Security: security alerts, secure scores, identity protection risk detections
- Devices: Intune-managed devices, compliance states, configuration profiles
- Email & Collaboration: mailbox activity, Teams activity, SharePoint/OneDrive access

Available Operations:
Microsoft Graph supports many operations beyond just reading data:
- READ operations: list, get (use specific helper tools or graph_operation_tool with explicit args)
- WRITE operations: create, update, delete (use graph_operation_tool or specific tools)
- ACTION operations: changePassword, revokeSignInSessions, invalidateAllRefreshTokens, etc.

Available Tools:
1. graph_operation_tool - Generic tool for operations (create, update, delete, actions, and explicit reads)
2. list_resource_operations_tool - Discover available operations for a resource type
3. Specific tools: create_user_tool, update_user_tool, delete_user_tool, change_user_password_tool, etc.
4. Directory-role helpers: 
   - list_user_directory_roles_tool (list a user’s directoryRole memberships)
   - remove_user_from_directory_role_tool (remove the user from a role)
5. Identity/device helpers:
   - list_user_registered_devices_tool (enumerate registered devices for a user)
   - list_managed_devices_for_user_tool / get_managed_device_tool / remote_lock_managed_device_tool / wipe_managed_device_tool / retire_managed_device_tool / delete_managed_device_record_tool / sync_managed_device_tool / rename_managed_device_tool / disable_lost_mode_tool
6. Group membership helpers:
   - list_user_groups_tool, add_user_to_group_direct_tool, remove_user_from_group_direct_tool
7. Visibility / telemetry helpers:
   - list_sign_in_logs_tool, list_directory_audits_tool, list_risky_users_tool, list_risk_detections_tool
8. Application / OAuth helpers:
   - list_recent_applications_tool, disable_service_principal_tool, list_service_principals_by_appid_tool, remove_application_password_tool, list_oauth_permission_grants_tool, delete_oauth_permission_grant_tool
9. Compliance & configuration:
    - list_device_compliance_policies_tool, get_device_compliance_state_summary_tool, list_device_configurations_tool
10. Mailbox helpers:
    - list_inbox_rules_tool, delete_inbox_rule_tool, search_user_messages_tool

Guidelines for constructing Graph API queries:
1. For READ operations: Prefer specific helper tools. If needed, use graph_operation_tool with explicit `resource_type`, `operation`, and ids/query params.
2. For WRITE/ACTION operations: Use graph_operation_tool or specific operation tools.
3. To discover operations: Use list_resource_operations_tool to see what's available for a resource.
4. For time-based queries, mention "last 7 days", "recent", or specific timeframes.
5. For filtering, mention specific criteria (e.g., "high severity", "failed sign-ins").
6. IMPORTANT: Not all properties are filterable. For security incidents, filterable properties include: severity, status, createdDateTime, lastUpdateDateTime, classification, determination, assignedTo, displayName, id.
7. Non-filterable properties for security incidents: redirectIncidentId, alerts (collection), tags (collection), description. If you need to filter by these, fetch all data and filter client-side.
8. For `/security/alerts_v2`, only use the optional query parameters `$count`, `$filter`, `$skip`, `$top`. This endpoint lets you filter on `assignedTo`, `classification`, `determination`, `createdDateTime`, `lastUpdateDateTime`, `severity`, `serviceSource`, and `status`. Avoid $filter on any other property to prevent errors.
9. If you need to query multiple resources, make separate tool calls.

Common query patterns:
- "Get all users in the organization" -> use graph_operation_tool(resource_type="users", operation="list", query_params={...}) or list helper tools
- "Create a new user" -> use create_user_tool or graph_operation_tool(resource_type="users", operation="create", body={{...}})
- "Update user John's job title" -> use update_user_tool or graph_operation_tool(resource_type="users", operation="update", resource_id="...", body={{...}})
- "Change password for user" -> use change_user_password_tool or graph_operation_tool(resource_type="users", operation="changePassword", ...)
- "Revoke all sessions for user" -> use revoke_user_signin_sessions_tool or graph_operation_tool(resource_type="users", operation="revokeSignInSessions", ...)
- "List a user's directory roles" -> use list_user_directory_roles_tool(user_id="...")
- "List registered/managed devices for a user" -> use list_user_registered_devices_tool or list_managed_devices_for_user_tool
- "Show sign-in logs for the last 7 days" -> use list_sign_in_logs_tool(filter_expr="createdDateTime ge ...")
- "List security alerts with high severity" -> use list_security_alerts_tool(severity="high")

Constraints:
- For WRITE operations, ensure you have the necessary permissions and user approval.
- Do not explain Graph API endpoints to the user. Instead, call the appropriate tool and answer based on results.
- Handle errors gracefully - if an operation fails, check permissions and parameters.
- Always prioritize security and privacy.
- Note that today is {today_date}

Use only the provided tools and information to construct your answers. Focus on clarity, precision, and relevance.
"""

GRAPH_QUERY_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", graph_query_system),
        MessagesPlaceholder(variable_name="graph_messages"),
    ]
)

####################################################################################################
## Codemode-Style Prompts


class CodemodeRouteDecision(BaseModel):
    """Structured output for codemode-style routing."""

    need_schema_lookup: bool = Field(
        default=False,
        description=(
            "Whether the request needs an explicit schema inspection step before executing "
            "the main Graph tool call."
        ),
    )
    expected_steps: Literal["single", "multi"] = Field(
        default="single",
        description="Estimate if the request can be handled in one tool round or needs multiple rounds.",
    )
    stop_after_first_success: bool = Field(
        default=True,
        description=(
            "If true, stop after a successful tool response that answers the user request."
        ),
    )
    reason: str = Field(
        default="",
        description="Short rationale for the routing decision.",
    )


class CodemodeEvaluation(BaseModel):
    """Structured output for codemode-style evaluator."""

    status: Literal["done", "continue"] = Field(
        default="done",
        description="Whether to finalize the response or run another tool iteration.",
    )
    reason: str = Field(
        default="",
        description="Short explanation for the evaluation decision.",
    )


codemode_query_system = """You are a Microsoft Graph execution worker.
Call the minimum necessary tool(s) to answer the user request accurately.

Rules:
- Prefer direct helper tools when available.
- For read/list/search queries, use specific helper tools first; otherwise use graph_operation_tool with explicit arguments.
- Use graph_operation_tool or specific helper tools for write/action requests.
- Avoid exploratory calls unless needed to disambiguate the request.
- If the request requires multiple resources, you may emit multiple tool calls.
- Do not provide a final user answer in this step; call tools only.
- Note that today is {today_date}
"""

CODEMODE_QUERY_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", codemode_query_system),
        MessagesPlaceholder(variable_name="graph_messages"),
    ]
)

codemode_router_system = """You are a routing planner for Microsoft Graph requests.
Given the conversation, decide:
1) whether schema lookup is needed before execution,
2) whether this is likely single-step or multi-step,
3) whether to stop after first successful tool response.

Use conservative routing:
- need_schema_lookup=true only when endpoint/resource ambiguity is high.
- expected_steps=multi when multiple dependent tool calls are likely.
- stop_after_first_success=true for most direct requests.
"""

CODEMODE_ROUTER_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", codemode_router_system),
        MessagesPlaceholder(variable_name="graph_messages"),
    ]
)

codemode_evaluator_system = """You are an execution evaluator for Microsoft Graph tool runs.
Decide whether the latest tool outputs are enough to answer the user request.

Return:
- status='done' when outputs are sufficient or further retries are unlikely to help.
- status='continue' only when another tool call is clearly needed.

Be strict about avoiding unnecessary extra iterations.
"""

CODEMODE_EVALUATOR_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", codemode_evaluator_system),
        MessagesPlaceholder(variable_name="graph_messages"),
    ]
)

####################################################################################################
## Final Response Generator Prompt

final_response_system = """You are an expert agent that provides clear, concise answers based on Microsoft Graph API query results.

Your task is to analyze the tool results and generate a natural language response that directly answers the user's question.

Guidelines:
1. Review the tool results carefully and extract relevant information
2. Format your response in a clear, user-friendly manner
3. If the results are empty or no data matches the query, explain this clearly
4. For user lists, present them in a readable format (e.g., table or bullet list)
5. Highlight key information that directly addresses the user's question
6. Be concise but complete - don't omit important details
7. If filtering was applied (e.g., by department), mention this in your response

Always base your answer solely on the tool results provided. Do not make up information.
"""

FINAL_RESPONSE_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", final_response_system),
        MessagesPlaceholder(variable_name="graph_messages"),
    ]
)

# GraphQueryParams and QUERY_PARSER_PROMPT were removed: they were only used by
# graph_query_beta_tool which has been removed. Beta-endpoint queries are now
# handled by graph_operation_tool with api_version=”beta”.
