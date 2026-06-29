from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph

from utils.agent_utils import (
    Agents,
    DFOutput,
    QueryOutput,
    State,
    create_tool_node_with_fallback,
    get_tool_call_args,
    get_tool_call_name,
)
from utils.llm_adapter import get_chat_model

from graph_agent.config import (
    get_codemode_context_messages,
    get_codemode_max_turns,
    get_codemode_tool_summary_chars,
    get_graph_execution_mode,
    is_codemode_parallel_reads_enabled,
)
from graph_agent.prompts import (
    CODEMODE_EVALUATOR_PROMPT,
    CODEMODE_QUERY_PROMPT,
    CODEMODE_ROUTER_PROMPT,
    FINAL_RESPONSE_PROMPT,
    GRAPH_QUERY_PROMPT,
    TABLE_SELECTION_PROMPT,
    CodemodeEvaluation,
    CodemodeRouteDecision,
)
from graph_agent.tools import (
    get_graph_resource_schema_tool,
    graph_operation_tool,
    list_resource_operations_tool,
    # User operations
    get_user_tool,
    create_user_tool,
    update_user_tool,
    delete_user_tool,
    change_user_password_tool,
    validate_user_password_tool,
    retry_user_service_provisioning_tool,
    convert_external_user_to_internal_tool,
    revoke_user_signin_sessions_tool,
    invalidate_user_refresh_tokens_tool,
    export_user_personal_data_tool,
    get_user_delta_tool,
    search_user_by_upn_tool,
    list_user_groups_tool,
    set_user_account_enabled_tool,
    reset_user_password_tool,
    list_user_registered_devices_tool,
    disable_directory_device_tool,
    list_user_directory_roles_tool,
    remove_user_from_directory_role_tool,
    add_user_to_group_direct_tool,
    remove_user_from_group_direct_tool,
    # Group operations
    list_groups_tool,
    get_group_tool,
    create_group_tool,
    update_group_tool,
    delete_group_tool,
    add_group_member_tool,
    remove_group_member_tool,
    add_group_owner_tool,
    remove_group_owner_tool,
    list_group_members_tool,
    list_group_owners_tool,
    # Application operations
    list_applications_tool,
    get_application_tool,
    create_application_tool,
    update_application_tool,
    delete_application_tool,
    # Device operations
    list_devices_tool,
    get_device_tool,
    delete_device_tool,
    list_managed_devices_for_user_tool,
    get_managed_device_tool,
    remote_lock_managed_device_tool,
    wipe_managed_device_tool,
    retire_managed_device_tool,
    delete_managed_device_record_tool,
    sync_managed_device_tool,
    rename_managed_device_tool,
    disable_lost_mode_tool,
    # Security operations
    list_security_alerts_tool,
    get_security_alert_tool,
    update_alert_tool,
    list_security_incidents_tool,
    get_security_incident_tool,
    update_incident_tool,
    update_secure_score_control_profile_tool,
    get_secure_score_tool,
    get_secure_score_control_profile_tool,
    get_ediscovery_case_operations_tool,
    list_identities_health_issues_tool,
    get_identities_health_issue_tool,
    update_identities_health_issue_tool,
    list_identities_sensors_tool,
    get_identities_sensor_tool,
    update_identities_sensor_tool,
    delete_identities_sensor_tool,
    # Attack Simulation operations
    list_attack_simulations_tool,
    get_attack_simulation_tool,
    create_attack_simulation_tool,
    update_attack_simulation_tool,
    delete_attack_simulation_tool,
    get_simulation_payload_tool,
    get_simulation_login_page_tool,
    get_simulation_landing_page_tool,
    # eDiscovery operations
    list_ediscovery_cases_tool,
    get_ediscovery_case_tool,
    create_ediscovery_case_tool,
    update_ediscovery_case_tool,
    delete_ediscovery_case_tool,
    # Secure Score operations
    list_secure_scores_tool,
    list_secure_score_control_profiles_tool,
    # Threat Intelligence operations
    list_threat_intelligence_indicators_tool,
    get_threat_intelligence_indicator_tool,
    create_threat_intelligence_indicator_tool,
    update_threat_intelligence_indicator_tool,
    delete_threat_intelligence_indicator_tool,
    # Threat Submission operations
    list_threat_submissions_tool,
    get_threat_submission_tool,
    create_threat_submission_tool,
    # Visibility / audit
    list_sign_in_logs_tool,
    list_directory_audits_tool,
    list_risky_users_tool,
    list_risk_detections_tool,
    # App / OAuth
    list_recent_applications_tool,
    disable_service_principal_tool,
    list_service_principals_by_appid_tool,
    remove_application_password_tool,
    list_oauth_permission_grants_tool,
    delete_oauth_permission_grant_tool,
    # Compliance / configuration
    list_device_compliance_policies_tool,
    get_device_compliance_state_summary_tool,
    list_device_configurations_tool,
    # Mailbox operations
    list_inbox_rules_tool,
    delete_inbox_rule_tool,
    search_user_messages_tool,
    make_graph_request,
)

llm = get_chat_model(verbose=True)

MISSING_TOOL_CALL_ERROR = (
    "Error: No Microsoft Graph tool was called. Always call one of the bound Graph "
    "tools (graph_operation_tool or a specific helper) before "
    "responding to the user."
)
MAX_TOOL_RETRIES = 2
MAX_TOOL_CALL_ID_LENGTH = 40

GRAPH_EXECUTION_MODE = get_graph_execution_mode()
CODEMODE_MAX_TURNS = get_codemode_max_turns()
CODEMODE_CONTEXT_MESSAGES = get_codemode_context_messages()
CODEMODE_TOOL_SUMMARY_CHARS = get_codemode_tool_summary_chars()
CODEMODE_PARALLEL_READS = is_codemode_parallel_reads_enabled()

USER_ID_TOOL_NAMES = {
    "get_user_tool",
    "create_user_tool",
    "update_user_tool",
    "delete_user_tool",
    "change_user_password_tool",
    "validate_user_password_tool",
    "retry_user_service_provisioning_tool",
    "convert_external_user_to_internal_tool",
    "revoke_user_signin_sessions_tool",
    "invalidate_user_refresh_tokens_tool",
    "export_user_personal_data_tool",
    "get_user_delta_tool",
    "search_user_by_upn_tool",
    "list_user_groups_tool",
    "set_user_account_enabled_tool",
    "reset_user_password_tool",
    "list_user_registered_devices_tool",
    "list_user_directory_roles_tool",
    "remove_user_from_directory_role_tool",
    "add_user_to_group_direct_tool",
    "remove_user_from_group_direct_tool",
    "list_managed_devices_for_user_tool",
    "list_inbox_rules_tool",
    "delete_inbox_rule_tool",
    "search_user_messages_tool",
}

READ_ONLY_TOOL_NAMES = {
    "list_resource_operations_tool",
    "get_graph_resource_schema_tool",
}
READ_ONLY_PREFIXES = ("get_", "list_", "search_")
MUTATING_PREFIXES = (
    "create_",
    "update_",
    "delete_",
    "change_",
    "set_",
    "reset_",
    "revoke_",
    "invalidate_",
    "export_",
    "convert_",
    "retry_",
    "add_",
    "remove_",
    "disable_",
    "wipe_",
    "retire_",
    "remote_",
    "sync_",
    "rename_",
)

GUID_PATTERN = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$"
)

ALL_GRAPH_TOOLS = [
    # Operation tools
    graph_operation_tool,
    list_resource_operations_tool,
    # User operations
    get_user_tool,
    create_user_tool,
    update_user_tool,
    delete_user_tool,
    change_user_password_tool,
    validate_user_password_tool,
    retry_user_service_provisioning_tool,
    convert_external_user_to_internal_tool,
    revoke_user_signin_sessions_tool,
    invalidate_user_refresh_tokens_tool,
    export_user_personal_data_tool,
    get_user_delta_tool,
    search_user_by_upn_tool,
    list_user_groups_tool,
    set_user_account_enabled_tool,
    reset_user_password_tool,
    list_user_registered_devices_tool,
    disable_directory_device_tool,
    list_user_directory_roles_tool,
    remove_user_from_directory_role_tool,
    add_user_to_group_direct_tool,
    remove_user_from_group_direct_tool,
    # Group operations
    list_groups_tool,
    get_group_tool,
    create_group_tool,
    update_group_tool,
    delete_group_tool,
    add_group_member_tool,
    remove_group_member_tool,
    add_group_owner_tool,
    remove_group_owner_tool,
    list_group_members_tool,
    list_group_owners_tool,
    # Application operations
    list_applications_tool,
    get_application_tool,
    create_application_tool,
    update_application_tool,
    delete_application_tool,
    # Device operations
    list_devices_tool,
    get_device_tool,
    delete_device_tool,
    list_managed_devices_for_user_tool,
    get_managed_device_tool,
    remote_lock_managed_device_tool,
    wipe_managed_device_tool,
    retire_managed_device_tool,
    delete_managed_device_record_tool,
    sync_managed_device_tool,
    rename_managed_device_tool,
    disable_lost_mode_tool,
    # Security operations
    list_security_alerts_tool,
    get_security_alert_tool,
    update_alert_tool,
    list_security_incidents_tool,
    get_security_incident_tool,
    update_incident_tool,
    update_secure_score_control_profile_tool,
    get_secure_score_tool,
    get_secure_score_control_profile_tool,
    get_ediscovery_case_operations_tool,
    list_identities_health_issues_tool,
    get_identities_health_issue_tool,
    update_identities_health_issue_tool,
    list_identities_sensors_tool,
    get_identities_sensor_tool,
    update_identities_sensor_tool,
    delete_identities_sensor_tool,
    # Attack Simulation operations
    list_attack_simulations_tool,
    get_attack_simulation_tool,
    create_attack_simulation_tool,
    update_attack_simulation_tool,
    delete_attack_simulation_tool,
    get_simulation_payload_tool,
    get_simulation_login_page_tool,
    get_simulation_landing_page_tool,
    # eDiscovery operations
    list_ediscovery_cases_tool,
    get_ediscovery_case_tool,
    create_ediscovery_case_tool,
    update_ediscovery_case_tool,
    delete_ediscovery_case_tool,
    # Secure Score operations
    list_secure_scores_tool,
    list_secure_score_control_profiles_tool,
    # Threat Intelligence operations
    list_threat_intelligence_indicators_tool,
    get_threat_intelligence_indicator_tool,
    create_threat_intelligence_indicator_tool,
    update_threat_intelligence_indicator_tool,
    delete_threat_intelligence_indicator_tool,
    # Threat Submission operations
    list_threat_submissions_tool,
    get_threat_submission_tool,
    create_threat_submission_tool,
    # Visibility / audit
    list_sign_in_logs_tool,
    list_directory_audits_tool,
    list_risky_users_tool,
    list_risk_detections_tool,
    # App / OAuth operations
    list_recent_applications_tool,
    disable_service_principal_tool,
    list_service_principals_by_appid_tool,
    remove_application_password_tool,
    list_oauth_permission_grants_tool,
    delete_oauth_permission_grant_tool,
    # Compliance / configuration
    list_device_compliance_policies_tool,
    get_device_compliance_state_summary_tool,
    list_device_configurations_tool,
    # Mailbox operations
    list_inbox_rules_tool,
    delete_inbox_rule_tool,
    search_user_messages_tool,
]

TOOL_MAP = {tool.name: tool for tool in ALL_GRAPH_TOOLS}


def _looks_like_object_id(candidate: str) -> bool:
    return bool(candidate and GUID_PATTERN.match(candidate))


def _looks_like_upn(candidate: str) -> bool:
    return bool(candidate and "@" in candidate)


def _resolve_user_identifier(raw_identifier: str | None) -> str | None:
    """Resolve a display name to an object ID / UPN via the Graph API.

    Returns the resolved identifier, or the original string on failure so the
    caller can still attempt the downstream tool call.
    """
    if not raw_identifier:
        return raw_identifier
    candidate = str(raw_identifier).strip()
    if _looks_like_object_id(candidate) or _looks_like_upn(candidate):
        return candidate

    escaped = candidate.replace("'", "''")
    filter_expr = (
        f"displayName eq '{escaped}' "
        f"or userPrincipalName eq '{escaped}' "
        f"or mail eq '{escaped}'"
    )
    try:
        result = make_graph_request(
            method="GET",
            endpoint="/users",
            params={"$filter": filter_expr, "$top": 1},
        )
        if isinstance(result, dict):
            if "error" in result:
                logger.warning(
                    "User identifier resolution returned an error for %r: %s",
                    candidate,
                    result["error"],
                )
                return candidate
            users = result.get("value") or []
            if users:
                user = users[0]
                resolved = (
                    user.get("id")
                    or user.get("userPrincipalName")
                    or user.get("mail")
                )
                if resolved:
                    logger.debug("Resolved %r → %r", candidate, resolved)
                    return resolved
    except Exception as exc:
        logger.warning("Failed to resolve user identifier %r: %s", candidate, exc)
    return candidate


def _preprocess_tool_args(tool_name: str | None, tool_args: dict | None) -> dict | None:
    if not tool_args or not tool_name:
        return tool_args

    if tool_name in USER_ID_TOOL_NAMES:
        for key in list(tool_args.keys()):
            if key in {"user_id", "directory_object_id", "member_id", "owner_id"} and tool_args[key]:
                resolved = _resolve_user_identifier(tool_args[key])
                if resolved:
                    tool_args[key] = resolved

    if tool_name == "graph_operation_tool":
        resource_type = (tool_args.get("resource_type") or "").lower()
        if resource_type == "users" and tool_args.get("operation") in {"update", "delete", "changePassword"}:
            resource_id = tool_args.get("resource_id")
            resolved = _resolve_user_identifier(resource_id)
            if resolved:
                tool_args["resource_id"] = resolved

    return tool_args


def _tool_call_id(tool_call: Any, index: int) -> str:
    candidate = None
    if isinstance(tool_call, dict):
        candidate = tool_call.get("id")
    else:
        candidate = getattr(tool_call, "id", None)

    if isinstance(candidate, str) and candidate:
        return candidate[:MAX_TOOL_CALL_ID_LENGTH]
    return f"tool_call_{index + 1}"


def _truncate_text(content: str, max_chars: int) -> str:
    if len(content) <= max_chars:
        return content
    return f"{content[:max_chars]} ...[truncated]"


def _normalize_response_payload(response: Any) -> tuple[str, Any, list[Any]]:
    content = response if isinstance(response, str) else json.dumps(response, default=str)
    parsed = None
    data: list[Any] = []

    try:
        parsed = json.loads(content) if isinstance(content, str) else response
    except Exception:
        parsed = None

    if isinstance(parsed, list):
        data = parsed
    elif isinstance(parsed, dict):
        if "error" in parsed:
            data = []
        elif isinstance(parsed.get("value"), list):
            data = parsed["value"]
        else:
            data = [parsed] if parsed else []

    return content, parsed, data


def _is_read_only_tool(tool_name: str | None) -> bool:
    if not tool_name:
        return False
    if tool_name in READ_ONLY_TOOL_NAMES:
        return True
    if tool_name.startswith(MUTATING_PREFIXES):
        return False
    if tool_name.startswith(READ_ONLY_PREFIXES):
        return True
    return False


def _tool_content_has_error(content: str | None) -> bool:
    raw = (content or "").strip()
    lowered = raw.lower()
    if lowered.startswith("error:"):
        return True

    try:
        parsed = json.loads(raw)
        return isinstance(parsed, dict) and "error" in parsed
    except Exception:
        return '"error"' in lowered


# Fields that must be preserved verbatim in compact summaries so downstream
# tool calls can reference them (e.g. step-2 needs the id from step-1).
_IDENTIFIER_FIELDS = {"id", "userPrincipalName", "mail", "groupId", "appId", "deviceId"}
_MAX_RECORDS_IN_SUMMARY = 10  # cap for multi-record summaries


def _extract_identifiers(record: dict) -> dict:
    """Return only the identifier fields present in a record."""
    return {k: v for k, v in record.items() if k in _IDENTIFIER_FIELDS}


def _compact_tool_content(content: str, max_chars: int) -> str:
    """Compress tool output for context while preserving identifiers needed by later steps."""
    trimmed = _truncate_text(content, max_chars)

    try:
        parsed = json.loads(content)
    except Exception:
        return trimmed

    if isinstance(parsed, dict) and "error" in parsed:
        error = parsed.get("error")
        if isinstance(error, dict):
            message = error.get("message") or str(error)
        else:
            message = str(error)
        return _truncate_text(f"Tool error: {message}", max_chars)

    records: list[Any] | None = None
    if isinstance(parsed, dict) and isinstance(parsed.get("value"), list):
        records = parsed["value"]
    elif isinstance(parsed, list):
        records = parsed

    if records is not None:
        first = records[0] if records else {}
        all_keys = list(first.keys())[:6] if isinstance(first, dict) else []
        # Preserve identifier fields from the first N records so step-2 can use them
        id_rows = [
            _extract_identifiers(r)
            for r in records[:_MAX_RECORDS_IN_SUMMARY]
            if isinstance(r, dict) and _extract_identifiers(r)
        ]
        summary = f"Returned {len(records)} records. Keys: {', '.join(all_keys) if all_keys else 'n/a'}."
        if id_rows:
            summary += f" Identifiers (first {len(id_rows)}): {json.dumps(id_rows)}"
        return _truncate_text(summary, max_chars)

    if isinstance(parsed, dict):
        keys = list(parsed.keys())[:10]
        id_fields = _extract_identifiers(parsed)
        summary = f"Returned object with keys: {', '.join(keys)}."
        if id_fields:
            summary += f" Identifiers: {json.dumps(id_fields)}"
        return _truncate_text(summary, max_chars)

    return trimmed


def _compact_graph_messages(messages: list[Any]) -> list[Any]:
    recent = list(messages or [])[-CODEMODE_CONTEXT_MESSAGES:]
    compacted: list[Any] = []

    for message in recent:
        if isinstance(message, ToolMessage):
            compacted.append(
                ToolMessage(
                    content=_compact_tool_content(str(message.content or ""), CODEMODE_TOOL_SUMMARY_CHARS),
                    tool_call_id=message.tool_call_id,
                    name=getattr(message, "name", None),
                )
            )
        elif isinstance(message, AIMessage):
            compacted.append(
                AIMessage(
                    content=_truncate_text(str(message.content or ""), CODEMODE_TOOL_SUMMARY_CHARS),
                    tool_calls=message.tool_calls,
                )
            )
        elif isinstance(message, HumanMessage):
            compacted.append(
                HumanMessage(content=_truncate_text(str(message.content or ""), CODEMODE_TOOL_SUMMARY_CHARS))
            )
        elif isinstance(message, SystemMessage):
            compacted.append(
                SystemMessage(content=_truncate_text(str(message.content or ""), CODEMODE_TOOL_SUMMARY_CHARS))
            )
        else:
            compacted.append(message)

    return compacted


def _build_query_input_state(state: State, codemode: bool) -> dict[str, Any]:
    llm_state = dict(state)
    llm_state["today_date"] = datetime.utcnow().strftime("%Y-%m-%d")
    if codemode:
        llm_state["graph_messages"] = _compact_graph_messages(list(state.get("graph_messages", [])))
    return llm_state


def _build_eval_input_state(state: State) -> dict[str, Any]:
    return {"graph_messages": _compact_graph_messages(list(state.get("graph_messages", [])))}


def _execute_single_tool_call(index: int, tool_call: Any) -> dict[str, Any]:
    tool_name = get_tool_call_name(tool_call)
    tool_call_id = _tool_call_id(tool_call, index)
    logger.debug("Executing tool %r (call_id=%s)", tool_name, tool_call_id)

    if not tool_name:
        return {
            "index": index,
            "tool_message": ToolMessage(
                content="Error: Tool call is missing a tool name.",
                tool_call_id=tool_call_id,
            ),
            "query_statement": None,
            "df": [],
        }

    if tool_name == "missing_tool_call_guard":
        return {
            "index": index,
            "tool_message": ToolMessage(
                content=MISSING_TOOL_CALL_ERROR,
                tool_call_id=tool_call_id,
            ),
            "query_statement": None,
            "df": [],
        }

    tool_args = get_tool_call_args(tool_call)
    tool_args = _preprocess_tool_args(tool_name, tool_args)

    tool_func = TOOL_MAP.get(tool_name)
    if not tool_func:
        return {
            "index": index,
            "tool_message": ToolMessage(
                content=f"Error: Unknown tool '{tool_name}'.",
                tool_call_id=tool_call_id,
            ),
            "query_statement": None,
            "df": [],
        }

    try:
        response = tool_func.invoke(tool_args or {})
        content, _parsed, data = _normalize_response_payload(response)
        logger.debug("Tool %r returned %d record(s)", tool_name, len(data))
        return {
            "index": index,
            "tool_message": ToolMessage(content=content, tool_call_id=tool_call_id, name=tool_name),
            "query_statement": None,
            "df": data,
        }
    except Exception as error:
        logger.error("Tool %r raised exception: %s", tool_name, error)
        return {
            "index": index,
            "tool_message": ToolMessage(
                content=json.dumps({"error": {"message": str(error)}}, indent=2),
                tool_call_id=tool_call_id,
                name=tool_name,
            ),
            "query_statement": None,
            "df": [],
        }


# LLM runners
tables_selector_llm = TABLE_SELECTION_PROMPT | llm.bind_tools(
    [get_graph_resource_schema_tool],
    parallel_tool_calls=False,
)

query_llm = GRAPH_QUERY_PROMPT | llm.bind_tools(
    ALL_GRAPH_TOOLS,
    parallel_tool_calls=False,
    tool_choice="required",
)

codemode_query_llm = CODEMODE_QUERY_PROMPT | llm.bind_tools(
    ALL_GRAPH_TOOLS,
    parallel_tool_calls=True,
    tool_choice="required",
)

final_response_llm = FINAL_RESPONSE_PROMPT | llm
codemode_router_llm = CODEMODE_ROUTER_PROMPT | llm.with_structured_output(CodemodeRouteDecision)
codemode_evaluator_llm = CODEMODE_EVALUATOR_PROMPT | llm.with_structured_output(CodemodeEvaluation)


def tables_selection_node(state: State):
    message = tables_selector_llm.invoke(state)
    tool_messages = []
    if message.tool_calls:
        for tc in message.tool_calls:
            if tc["name"] != "get_graph_resource_schema_tool":
                tool_messages.append(
                    ToolMessage(
                        content=(
                            f"Error: Wrong tool called: {tc['name']}. "
                            "Only call get_graph_resource_schema_tool to inspect Microsoft Graph API resources."
                        ),
                        tool_call_id=tc["id"],
                    )
                )
    return {"graph_messages": [message] + tool_messages}


def _query_gen_core(state: State, codemode: bool):
    llm_state = _build_query_input_state(state, codemode=codemode)
    runner = codemode_query_llm if codemode else query_llm
    message = runner.invoke(llm_state)
    updates: list[Any] = [message]

    has_tool_history = any(isinstance(msg, ToolMessage) for msg in state.get("graph_messages", []))

    if not getattr(message, "tool_calls", None) and not has_tool_history:
        existing_errors = sum(
            1
            for msg in state.get("graph_messages", [])
            if isinstance(msg, ToolMessage) and (msg.content or "").startswith(MISSING_TOOL_CALL_ERROR)
        )

        if existing_errors >= MAX_TOOL_RETRIES:
            failure_response = AIMessage(
                content=(
                    "I couldn't complete the Microsoft Graph request because I failed to call "
                    "the required tool multiple times. Please rephrase your request or try again."
                ),
            )
            updates.append(failure_response)
        else:
            guard_id = getattr(message, "id", "") or ""
            if len(guard_id) > MAX_TOOL_CALL_ID_LENGTH or not guard_id:
                guard_id = f"missing_tool_call_{existing_errors + 1}"
            if len(guard_id) > MAX_TOOL_CALL_ID_LENGTH:
                guard_id = guard_id[:MAX_TOOL_CALL_ID_LENGTH]

            guard_call = {
                "id": guard_id,
                "name": "missing_tool_call_guard",
                "type": "tool_call",
                "args": {},
            }

            updates.append(AIMessage(content="", tool_calls=[guard_call]))
            updates.append(ToolMessage(content=MISSING_TOOL_CALL_ERROR, tool_call_id=guard_id))

    return {"graph_messages": updates}


def query_gen_node(state: State):
    return _query_gen_core(state, codemode=False)


def codemode_query_gen_node(state: State):
    return _query_gen_core(state, codemode=True)


def final_response_node(state: State):
    """Generate a final human-readable response based on tool results."""
    if GRAPH_EXECUTION_MODE == "codemode":
        message = final_response_llm.invoke(_build_eval_input_state(state))
    else:
        message = final_response_llm.invoke(state)
    return {"graph_messages": [message]}


def query_node(state: State):
    messages = state["graph_messages"]
    last_message = messages[-1]

    if not (isinstance(last_message, AIMessage) and last_message.tool_calls):
        return {}

    tool_calls = list(last_message.tool_calls)
    if not tool_calls:
        return {}

    if (
        CODEMODE_PARALLEL_READS
        and len(tool_calls) > 1
        and all(_is_read_only_tool(get_tool_call_name(tool_call)) for tool_call in tool_calls)
    ):
        with ThreadPoolExecutor(max_workers=min(4, len(tool_calls))) as executor:
            futures = {
                executor.submit(_execute_single_tool_call, index, tool_call): index
                for index, tool_call in enumerate(tool_calls)
            }
            results = [future.result() for future in as_completed(futures)]
        results.sort(key=lambda item: item["index"])
    else:
        results = [_execute_single_tool_call(index, tool_call) for index, tool_call in enumerate(tool_calls)]

    tool_messages = [item["tool_message"] for item in results]
    combined_df: list[Any] = []
    query_statements = [item["query_statement"] for item in results if item.get("query_statement")]

    for item in results:
        combined_df.extend(item.get("df") or [])

    updates: dict[str, Any] = {
        "graph_messages": tool_messages,
        "df": [
            DFOutput(
                agent=Agents.GraphAgent,
                df=combined_df,
            )
        ],
        "codemode_turn": int(state.get("codemode_turn") or 0) + 1,
    }

    if query_statements:
        updates["query_statement"] = [
            QueryOutput(
                agent=Agents.GraphAgent,
                query_statement=" | ".join(query_statements),
            )
        ]

    return updates


def codemode_router_node(state: State):
    compact_state = _build_eval_input_state(state)
    try:
        decision = codemode_router_llm.invoke(compact_state)
        logger.debug(
            "Router decision: schema=%s steps=%s stop_on_success=%s — %s",
            decision.need_schema_lookup,
            decision.expected_steps,
            decision.stop_after_first_success,
            decision.reason,
        )
    except Exception as exc:
        logger.warning("Router LLM failed: %s; using conservative defaults", exc)
        decision = CodemodeRouteDecision(
            need_schema_lookup=False,
            expected_steps="single",
            stop_after_first_success=True,
            reason="Router fallback: defaulting to direct execution.",
        )

    return {
        "codemode_requires_schema": bool(decision.need_schema_lookup),
        "codemode_stop_after_success": bool(decision.stop_after_first_success),
        "codemode_route_reason": decision.reason,
        "codemode_turn": 0,
    }


def codemode_evaluator_node(state: State):
    """Decide whether to finalize or run another tool iteration.

    Short-circuit order (fastest → most expensive):
    1. stop_after_first_success policy with a clean tool result  → done (no LLM call)
    2. max-turns guard                                           → done (no LLM call)
    3. LLM evaluator                                             → done | continue
    """
    latest_tool_message = next(
        (msg for msg in reversed(state.get("graph_messages", [])) if isinstance(msg, ToolMessage)),
        None,
    )

    # 1. Stop-after-success: most queries are single-step; skip the LLM call entirely.
    stop_after_success = bool(state.get("codemode_stop_after_success", True))
    if latest_tool_message and stop_after_success and not _tool_content_has_error(latest_tool_message.content):
        logger.debug("Evaluator: stop-after-first-success triggered")
        return {
            "codemode_eval_status": "done",
            "codemode_eval_reason": "Stop-after-first-success policy triggered.",
        }

    # 2. Max-turns guard.
    turns = int(state.get("codemode_turn") or 0)
    if turns >= CODEMODE_MAX_TURNS:
        logger.debug("Evaluator: max turns (%d) reached", CODEMODE_MAX_TURNS)
        return {
            "codemode_eval_status": "done",
            "codemode_eval_reason": f"Reached max turns ({CODEMODE_MAX_TURNS}).",
        }

    # 3. LLM evaluator for multi-step or error-recovery scenarios.
    try:
        verdict = codemode_evaluator_llm.invoke(_build_eval_input_state(state))
        status = verdict.status if verdict.status in {"done", "continue"} else "done"
        logger.debug("Evaluator LLM verdict: %s — %s", status, verdict.reason)
        return {
            "codemode_eval_status": status,
            "codemode_eval_reason": verdict.reason,
        }
    except Exception as exc:
        logger.warning("Evaluator LLM failed: %s; defaulting to done", exc)
        return {
            "codemode_eval_status": "done",
            "codemode_eval_reason": "Evaluator fallback on LLM failure.",
        }


def should_get_schema_classic(state: State):
    messages = state["graph_messages"]
    last_message = messages[-1]
    if isinstance(last_message, AIMessage):
        if last_message.tool_calls:
            return "get_resource_schema"
        return "query_gen_llm"
    return END


def should_get_schema_codemode(state: State):
    messages = state["graph_messages"]
    last_message = messages[-1]
    if isinstance(last_message, AIMessage):
        if last_message.tool_calls:
            return "get_resource_schema"
        return "codemode_query_gen_llm"
    return "codemode_query_gen_llm"


def should_continue_after_classic_query_generation(state: State):
    messages = state["graph_messages"]
    last_message = messages[-1]
    if isinstance(last_message, AIMessage):
        if last_message.tool_calls:
            return "execute_query"
        has_tool_history = any(isinstance(msg, ToolMessage) for msg in messages)
        return "final_response" if has_tool_history else END
    if isinstance(last_message, ToolMessage):
        return "query_gen_llm"
    return END


def should_continue_after_codemode_query_generation(state: State):
    messages = state["graph_messages"]
    last_message = messages[-1]
    if isinstance(last_message, AIMessage):
        if last_message.tool_calls:
            return "execute_query"
        has_tool_history = any(isinstance(msg, ToolMessage) for msg in messages)
        return "final_response" if has_tool_history else END
    if isinstance(last_message, ToolMessage):
        return "codemode_query_gen_llm"
    return END


def should_codemode_use_schema(state: State):
    if state.get("codemode_requires_schema"):
        return "table_selection_llm"
    return "codemode_query_gen_llm"


def should_codemode_continue(state: State):
    if int(state.get("codemode_turn") or 0) >= CODEMODE_MAX_TURNS:
        return "final_response"

    status = str(state.get("codemode_eval_status") or "done").lower()
    if status == "continue":
        return "codemode_query_gen_llm"
    return "final_response"


def build_classic_workflow() -> StateGraph:
    graph_workflow = StateGraph(State)
    graph_workflow.add_node(
        "get_resource_schema",
        create_tool_node_with_fallback([get_graph_resource_schema_tool], "graph_messages"),
    )
    graph_workflow.add_node("execute_query", query_node)
    graph_workflow.add_node("table_selection_llm", tables_selection_node)
    graph_workflow.add_node("query_gen_llm", query_gen_node)
    graph_workflow.add_node("final_response", final_response_node)

    graph_workflow.add_edge(START, "table_selection_llm")
    graph_workflow.add_conditional_edges("table_selection_llm", should_get_schema_classic)
    graph_workflow.add_edge("get_resource_schema", "query_gen_llm")
    graph_workflow.add_conditional_edges("query_gen_llm", should_continue_after_classic_query_generation)
    graph_workflow.add_edge("execute_query", "final_response")
    graph_workflow.add_edge("final_response", END)

    return graph_workflow


def build_codemode_workflow() -> StateGraph:
    graph_workflow = StateGraph(State)
    graph_workflow.add_node(
        "get_resource_schema",
        create_tool_node_with_fallback([get_graph_resource_schema_tool], "graph_messages"),
    )
    graph_workflow.add_node("table_selection_llm", tables_selection_node)
    graph_workflow.add_node("codemode_router", codemode_router_node)
    graph_workflow.add_node("codemode_query_gen_llm", codemode_query_gen_node)
    graph_workflow.add_node("execute_query", query_node)
    graph_workflow.add_node("codemode_evaluator", codemode_evaluator_node)
    graph_workflow.add_node("final_response", final_response_node)

    graph_workflow.add_edge(START, "codemode_router")
    graph_workflow.add_conditional_edges("codemode_router", should_codemode_use_schema)
    graph_workflow.add_conditional_edges("table_selection_llm", should_get_schema_codemode)
    graph_workflow.add_edge("get_resource_schema", "codemode_query_gen_llm")
    graph_workflow.add_conditional_edges("codemode_query_gen_llm", should_continue_after_codemode_query_generation)
    graph_workflow.add_edge("execute_query", "codemode_evaluator")
    graph_workflow.add_conditional_edges("codemode_evaluator", should_codemode_continue)
    graph_workflow.add_edge("final_response", END)

    return graph_workflow


if GRAPH_EXECUTION_MODE == "codemode":
    graph_graph = build_codemode_workflow().compile()
else:
    graph_graph = build_classic_workflow().compile()
