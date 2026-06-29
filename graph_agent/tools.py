import json
import logging
import os
import re
import threading
import time
from typing import Any, Dict, List, Optional

import httpx
from langchain_core.tools import tool
from msal import ConfidentialClientApplication

from graph_agent.config import get_graph_config
from graph_agent.operations_registry import (
    get_operation,
    list_resource_operations,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Alert filter constants (defined exactly once)
# ---------------------------------------------------------------------------

ALERTS_V2_FILTERABLE_PROPS = [
    "assignedTo",
    "classification",
    "determination",
    "createdDateTime",
    "lastUpdateDateTime",
    "severity",
    "serviceSource",
    "status",
]

ALERTS_V2_FILTERABLE_DESCRIPTION = (
    f"{', '.join(ALERTS_V2_FILTERABLE_PROPS[:-1])}, and {ALERTS_V2_FILTERABLE_PROPS[-1]}"
)

SERVICE_SOURCE_FILTER_PATTERN = re.compile(
    r"serviceSource\s+eq\s+'([^']+)'",
    flags=re.IGNORECASE,
)

VENDOR_FILTER_PATTERN = re.compile(
    r"vendorInformation/(?:provider|vendor)\s+eq\s+'([^']+)'",
    flags=re.IGNORECASE,
)


def canonical_service_source(value: str) -> str:
    normalized = value.strip()
    lowered = normalized.casefold()
    if "microsoft" in lowered and "defender" in lowered:
        return "microsoftDefenderForEndpoint"
    return normalized


def sanitize_alerts_v2_filter(filter_expression: str) -> str:
    def replace_service(match: re.Match[str]) -> str:
        return f"serviceSource eq '{canonical_service_source(match.group(1))}'"

    sanitized = SERVICE_SOURCE_FILTER_PATTERN.sub(replace_service, filter_expression)
    sanitized = VENDOR_FILTER_PATTERN.sub(
        lambda m: f"serviceSource eq '{canonical_service_source(m.group(1))}'",
        sanitized,
    )
    return sanitized


# ---------------------------------------------------------------------------
# MSAL client + token cache (thread-safe, single client instance per tenant)
# ---------------------------------------------------------------------------

_token_lock = threading.Lock()
_token_cache: Dict[str, Any] = {}   # cache_key → {"access_token": str, "expires_at": float}
_msal_clients: Dict[str, ConfidentialClientApplication] = {}  # cache_key → client


def _get_msal_client(tenant_id: str, client_id: str, client_secret: str) -> ConfidentialClientApplication:
    """Return a cached MSAL ConfidentialClientApplication (one per credential set)."""
    cache_key = f"{tenant_id}_{client_id}"
    if cache_key not in _msal_clients:
        _msal_clients[cache_key] = ConfidentialClientApplication(
            client_id=client_id,
            client_credential=client_secret,
            authority=f"https://login.microsoftonline.com/{tenant_id}",
        )
    return _msal_clients[cache_key]


def get_access_token() -> str:
    """Return a valid Microsoft Graph access token, refreshing when needed.

    Thread-safe: uses a lock so concurrent requests don't race to refresh the token.
    Reuses the same MSAL client to leverage its built-in token cache.
    """
    config = get_graph_config()
    tenant_id = config["tenant_id"]
    client_id = config["client_id"]
    client_secret = config["client_secret"]
    scopes = config["scopes"]

    if not all([tenant_id, client_id, client_secret]):
        raise ValueError(
            "Missing Graph API configuration. Set GRAPH_TENANT_ID, "
            "GRAPH_CLIENT_ID, and GRAPH_CLIENT_SECRET environment variables."
        )

    cache_key = f"{tenant_id}_{client_id}"

    with _token_lock:
        cached = _token_cache.get(cache_key)
        if cached and cached.get("expires_at", 0) > time.time():
            return cached["access_token"]

        app = _get_msal_client(tenant_id, client_id, client_secret)
        result = app.acquire_token_for_client(scopes=scopes)

        if "access_token" not in result:
            error = result.get("error_description") or result.get("error")
            raise ValueError(f"Failed to acquire Graph access token: {error}")

        expires_in = result.get("expires_in", 3600)
        _token_cache[cache_key] = {
            "access_token": result["access_token"],
            "expires_at": time.time() + expires_in - 60,  # 60-second safety margin
        }
        logger.debug("Acquired new Graph access token for tenant %s", tenant_id)
        return result["access_token"]


# ---------------------------------------------------------------------------
# Core HTTP helper with retry + back-off
# ---------------------------------------------------------------------------

_RETRY_STATUS_CODES = {429, 500, 502, 503, 504}
_MAX_RETRIES = 3
_BACKOFF_BASE = 1.5  # seconds


def make_graph_request(
    method: str,
    endpoint: str,
    json_data: Optional[Dict[str, Any]] = None,
    params: Optional[Dict[str, Any]] = None,
    api_version: str = "v1.0",
) -> Any:
    """Make an authenticated HTTP request to Microsoft Graph API.

    Retries up to ``_MAX_RETRIES`` times on transient errors (429, 5xx),
    honouring the ``Retry-After`` header when present.

    Args:
        method: HTTP method (GET, POST, PATCH, DELETE).
        endpoint: API endpoint path (e.g. "/users", "/users/{id}").
        json_data: Optional JSON body for POST/PATCH requests.
        params: Optional OData query parameters.
        api_version: "v1.0" (default) or "beta".

    Returns:
        Parsed JSON response as dict/list, or an error dict.
    """
    base_url = f"https://graph.microsoft.com/{api_version}"
    url = f"{base_url}{endpoint}"

    last_error: Exception | None = None

    for attempt in range(_MAX_RETRIES):
        access_token = get_access_token()
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.request(
                    method=method,
                    url=url,
                    headers=headers,
                    json=json_data,
                    params=params,
                )

            if response.status_code == 204:
                return {"success": True, "message": "Operation completed successfully"}

            if response.status_code in _RETRY_STATUS_CODES:
                retry_after = float(response.headers.get("Retry-After", _BACKOFF_BASE * (2 ** attempt)))
                logger.warning(
                    "Graph API transient error %s on %s %s (attempt %d/%d); retrying in %.1fs",
                    response.status_code,
                    method,
                    endpoint,
                    attempt + 1,
                    _MAX_RETRIES,
                    retry_after,
                )
                time.sleep(min(retry_after, 30))
                continue

            try:
                return response.json()
            except json.JSONDecodeError:
                return {"error": {"message": f"Invalid JSON response: {response.text}"}}

        except httpx.TransportError as exc:
            last_error = exc
            wait = _BACKOFF_BASE * (2 ** attempt)
            logger.warning(
                "Graph API network error on %s %s (attempt %d/%d): %s; retrying in %.1fs",
                method,
                endpoint,
                attempt + 1,
                _MAX_RETRIES,
                exc,
                wait,
            )
            time.sleep(wait)

    raise RuntimeError(
        f"Graph API request {method} {endpoint} failed after {_MAX_RETRIES} attempts: {last_error}"
    )


@tool
def get_graph_resource_schema_tool(resource_name: str) -> dict:
    """
    Get the schema (available fields) for a Microsoft Graph API resource.
    
    Args:
        resource_name: Name of the resource (e.g., "users", "groups", "auditLogs/signIns")
    
    Returns:
        dict: Schema information including available fields and their types
    """
    try:
        # Try to get a sample record to infer schema
        endpoint = f"/{resource_name}"
        params = {"$top": 1}

        result = make_graph_request("GET", endpoint, params=params)

        if isinstance(result, dict) and "value" in result and len(result["value"]) > 0:
            sample = result["value"][0]
            return {
                "resource": resource_name,
                "fields": list(sample.keys()),
                "sample": sample,
            }
        elif isinstance(result, list) and len(result) > 0:
            return {
                "resource": resource_name,
                "fields": list(result[0].keys()),
                "sample": result[0],
            }
        else:
            return {
                "resource": resource_name,
                "fields": [],
                "message": "No sample data available to infer schema",
            }
    except Exception as e:
        return {"error": {"message": str(e)}}


@tool
def update_alert_tool(alert_id: str, update_data: dict) -> str:
    """
    Update a security alert by ID.
    
    Args:
        alert_id: The ID of the alert to update
        update_data: Dictionary containing fields to update (e.g., {"status": "resolved", "assignedTo": "user@domain.com"})
    
    Returns:
        str: JSON string containing the updated alert or error information
    """
    try:
        endpoint = f"/security/alerts_v2/{alert_id}"
        result = make_graph_request("PATCH", endpoint, json_data=update_data)
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": {"message": str(e)}}, indent=2)


@tool
def update_incident_tool(incident_id: str, update_data: dict) -> str:
    """
    Update a security incident by ID.
    
    Args:
        incident_id: The ID of the incident to update
        update_data: Dictionary containing fields to update (e.g., {"status": "resolved", "assignedTo": "user@domain.com"})
    
    Returns:
        str: JSON string containing the updated incident or error information
    """
    try:
        endpoint = f"/security/incidents/{incident_id}"
        result = make_graph_request("PATCH", endpoint, json_data=update_data)
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": {"message": str(e)}}, indent=2)


@tool
def update_secure_score_control_profile_tool(profile_id: str, update_data: dict) -> str:
    """
    Update a secure score control profile by ID.
    
    Args:
        profile_id: The ID of the secure score control profile to update
        update_data: Dictionary containing fields to update (e.g., {"controlStateUpdates": [...]})
    
    Returns:
        str: JSON string containing the updated profile or error information
    """
    try:
        endpoint = f"/security/secureScoreControlProfiles/{profile_id}"
        result = make_graph_request("PATCH", endpoint, json_data=update_data)
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": {"message": str(e)}}, indent=2)


@tool
def get_secure_score_tool(secure_score_id: str) -> str:
    """
    Get a specific secure score by ID.
    
    Args:
        secure_score_id: The ID of the secure score to retrieve
    
    Returns:
        str: JSON string containing the secure score details or error information
    """
    try:
        endpoint = f"/security/secureScores/{secure_score_id}"
        result = make_graph_request("GET", endpoint)
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": {"message": str(e)}}, indent=2)


@tool
def get_secure_score_control_profile_tool(profile_id: str) -> str:
    """
    Get a specific secure score control profile by ID.
    
    Args:
        profile_id: The ID of the secure score control profile to retrieve
    
    Returns:
        str: JSON string containing the profile details or error information
    """
    try:
        endpoint = f"/security/secureScoreControlProfiles/{profile_id}"
        result = make_graph_request("GET", endpoint)
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": {"message": str(e)}}, indent=2)


@tool
def get_ediscovery_case_operations_tool(case_id: str) -> str:
    """
    List operations for a specific eDiscovery case.
    
    Args:
        case_id: The ID of the eDiscovery case
    
    Returns:
        str: JSON string containing the list of operations or error information
    """
    try:
        endpoint = f"/security/cases/ediscoveryCases/{case_id}/operations"
        result = make_graph_request("GET", endpoint)
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": {"message": str(e)}}, indent=2)


# graph_query_beta_tool was removed: it spun up an extra LLM inside a tool,
# was never added to ALL_GRAPH_TOOLS, and is superseded by graph_operation_tool
# with api_version="beta".


@tool
def graph_operation_tool(
    resource_type: str,
    operation: str,
    resource_id: Optional[str] = None,
    path_params: Optional[Dict[str, Any]] = None,
    body: Optional[Dict[str, Any]] = None,
    query_params: Optional[Dict[str, Any]] = None,
    api_version: str = "v1.0",
) -> str:
    """
    Execute a generic Microsoft Graph API operation (create, update, delete, action).
    
    Args:
        resource_type: The type of resource (e.g., "users", "groups", "security/alerts").
        operation: The specific operation to perform (e.g., "create", "update", "delete", "changePassword").
        resource_id: The ID of the specific resource if the operation is on a single resource (e.g., user ID).
        path_params: Optional extra path params used to fill endpoint templates (e.g., {"memberId": "..."}).
        body: The JSON request body for POST/PATCH operations.
        query_params: Optional query parameters for the request.
        api_version: API version to use - "v1.0" (default) or "beta".
    
    Returns:
        str: JSON string containing the operation results or error information.
    """
    try:
        op_details = get_operation(resource_type, operation)
        if not op_details:
            return json.dumps({"error": {"message": f"Operation '{operation}' not found for resource type '{resource_type}'"}}, indent=2)

        method = op_details["method"]
        endpoint_template = op_details["endpoint"]

        # Replace placeholders in the endpoint.
        # The registry uses "{id}" for single-resource operations (e.g., "/users/{id}"),
        # while callers often supply "resource_id". Support both to avoid KeyError("id").
        endpoint = endpoint_template
        if "{" in endpoint_template and "}" in endpoint_template:
            format_kwargs: Dict[str, Any] = {}
            if isinstance(path_params, dict):
                format_kwargs.update(path_params)
            if resource_id is not None:
                format_kwargs.setdefault("id", resource_id)
                format_kwargs.setdefault("resource_id", resource_id)
            try:
                endpoint = endpoint_template.format(**format_kwargs)
            except KeyError as e:
                missing = e.args[0] if e.args else "unknown"
                return json.dumps(
                    {
                        "error": {
                            "message": (
                                f"Missing path parameter '{missing}' required to format endpoint "
                                f"'{endpoint_template}'. Provide 'resource_id' for '{{id}}' or pass "
                                f"'path_params' with the missing key."
                            )
                        }
                    },
                    indent=2,
                )

        result = make_graph_request(
            method=method,
            endpoint=endpoint,
            json_data=body,
            params=query_params,
            api_version=api_version,
        )
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": {"message": str(e)}}, indent=2)


@tool
def list_resource_operations_tool(resource_type: str) -> str:
    """
    List all available operations for a specific resource type.

    Args:
        resource_type: The resource type (e.g., "users", "groups", "applications")

    Returns:
        str: JSON string containing list of available operations with their metadata
    """
    try:
        operations = list_resource_operations(resource_type)
        return json.dumps(operations, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": {"message": str(e)}}, indent=2)


# ============================================================================
# User Operations
# ============================================================================

@tool
def create_user_tool(user_data: Dict[str, Any]) -> str:
    """
    Create a new user in Azure AD.
    
    Args:
        user_data: Dictionary containing user properties (e.g., {"accountEnabled": true, "displayName": "John Doe", "mailNickname": "johndoe", "userPrincipalName": "johndoe@domain.com", "passwordProfile": {"password": "...", "forceChangePasswordNextSignIn": true}})
    
    Returns:
        str: JSON string containing the created user or error information
    """
    return graph_operation_tool.invoke({
        "resource_type": "users",
        "operation": "create",
        "body": user_data,
    })


@tool
def update_user_tool(user_id: str, update_data: Dict[str, Any]) -> str:
    """
    Update properties of an existing user.
    
    Args:
        user_id: The ID or userPrincipalName of the user to update
        update_data: Dictionary containing fields to update (e.g., {"jobTitle": "Manager", "department": "Engineering"})
    
    Returns:
        str: JSON string containing the updated user or error information
    """
    return graph_operation_tool.invoke({
        "resource_type": "users",
        "operation": "update",
        "resource_id": user_id,
        "body": update_data,
    })


@tool
def delete_user_tool(user_id: str) -> str:
    """
    Delete a user from Azure AD.
    
    Args:
        user_id: The ID or userPrincipalName of the user to delete
    
    Returns:
        str: JSON string containing success message or error information
    """
    return graph_operation_tool.invoke({
        "resource_type": "users",
        "operation": "delete",
        "resource_id": user_id,
    })


@tool
def get_user_tool(user_id: str, select_fields: Optional[List[str]] = None) -> str:
    """
    Get a specific user by ID or userPrincipalName.
    
    Args:
        user_id: The ID or userPrincipalName of the user
        select_fields: Optional list of fields to select (e.g., ["id", "displayName", "mail", "jobTitle"])
    
    Returns:
        str: JSON string containing the user data or error information
    """
    params = {}
    if select_fields:
        params["$select"] = ",".join(select_fields)
    
    return graph_operation_tool.invoke({
        "resource_type": "users",
        "operation": "get",
        "resource_id": user_id,
        "query_params": params if params else None,
    })


@tool
def change_user_password_tool(user_id: str, current_password: str, new_password: str) -> str:
    """
    Change a user's password.
    
    Args:
        user_id: The ID or userPrincipalName of the user
        current_password: The user's current password
        new_password: The new password to set
    
    Returns:
        str: JSON string containing success message or error information
    """
    return graph_operation_tool.invoke({
        "resource_type": "users",
        "operation": "changePassword",
        "resource_id": user_id,
        "body": {
            "currentPassword": current_password,
            "newPassword": new_password,
        },
    })


@tool
def validate_user_password_tool(user_id: str, password: str) -> str:
    """
    Validate password strength and compliance for a user.
    
    Args:
        user_id: The ID or userPrincipalName of the user
        password: The password to validate
    
    Returns:
        str: JSON string containing validation results or error information
    """
    return graph_operation_tool.invoke({
        "resource_type": "users",
        "operation": "validatePassword",
        "resource_id": user_id,
        "body": {
            "password": password,
        },
    })


@tool
def retry_user_service_provisioning_tool(user_id: str) -> str:
    """
    Retry service provisioning for a user.
    
    Args:
        user_id: The ID or userPrincipalName of the user
    
    Returns:
        str: JSON string containing success message or error information
    """
    return graph_operation_tool.invoke({
        "resource_type": "users",
        "operation": "retryServiceProvisioning",
        "resource_id": user_id,
    })


@tool
def convert_external_user_to_internal_tool(user_id: str) -> str:
    """
    Convert an external user to an internal member user.
    
    Args:
        user_id: The ID or userPrincipalName of the user
    
    Returns:
        str: JSON string containing success message or error information
    """
    return graph_operation_tool.invoke({
        "resource_type": "users",
        "operation": "convertExternalToInternal",
        "resource_id": user_id,
    })


@tool
def revoke_user_signin_sessions_tool(user_id: str) -> str:
    """
    Revoke all sign-in sessions for a user, forcing them to sign in again.
    
    Args:
        user_id: The ID or userPrincipalName of the user
    
    Returns:
        str: JSON string containing success message or error information
    """
    return graph_operation_tool.invoke({
        "resource_type": "users",
        "operation": "revokeSignInSessions",
        "resource_id": user_id,
    })


@tool
def invalidate_user_refresh_tokens_tool(user_id: str) -> str:
    """
    Invalidate all refresh tokens issued to applications for a user.
    
    Args:
        user_id: The ID or userPrincipalName of the user
    
    Returns:
        str: JSON string containing success message or error information
    """
    return graph_operation_tool.invoke({
        "resource_type": "users",
        "operation": "invalidateAllRefreshTokens",
        "resource_id": user_id,
    })


@tool
def export_user_personal_data_tool(user_id: str, storage_location: str) -> str:
    """
    Export a user's personal data for compliance.
    
    Args:
        user_id: The ID or userPrincipalName of the user
        storage_location: The storage location where the data should be exported
    
    Returns:
        str: JSON string containing success message or error information
    """
    return graph_operation_tool.invoke({
        "resource_type": "users",
        "operation": "exportPersonalData",
        "resource_id": user_id,
        "body": {
            "storageLocation": storage_location,
        },
    })


@tool
def get_user_delta_tool(delta_token: Optional[str] = None, select_fields: Optional[List[str]] = None) -> str:
    """
    Get incremental changes to users (delta query).
    
    Args:
        delta_token: Optional delta token from a previous delta query to get changes since that point
        select_fields: Optional list of fields to select
    
    Returns:
        str: JSON string containing changed users and a nextLink/deltaToken for subsequent queries
    """
    params = {}
    if delta_token:
        params["$deltatoken"] = delta_token
    if select_fields:
        params["$select"] = ",".join(select_fields)
    
    return graph_operation_tool.invoke({
        "resource_type": "users",
        "operation": "getDelta",
        "query_params": params if params else None,
    })


# ============================================================================
# Additional Identity / Directory Operations
# ============================================================================


@tool
def search_user_by_upn_tool(user_principal_name: str) -> str:
    """
    Search for a user by UPN/email using $filter.
    """
    params = {"$filter": f"userPrincipalName eq '{user_principal_name}'"}
    try:
        result = make_graph_request("GET", "/users", params=params)
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": {"message": str(e)}}, indent=2)


@tool
def list_user_groups_tool(user_id: str) -> str:
    """
    List all groups the specified user is a member of.
    """
    try:
        endpoint = f"/users/{user_id}/memberOf"
        result = make_graph_request("GET", endpoint)
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": {"message": str(e)}}, indent=2)


@tool
def set_user_account_enabled_tool(user_id: str, account_enabled: bool) -> str:
    """
    Enable or disable a user's sign-in (accountEnabled flag).
    """
    return graph_operation_tool.invoke({
        "resource_type": "users",
        "operation": "update",
        "resource_id": user_id,
        "body": {"accountEnabled": account_enabled},
    })


@tool
def reset_user_password_tool(user_id: str, new_password: str, force_change_next_sign_in: bool = True) -> str:
    """
    Reset a user's password (admin reset) and optionally force password change at next sign-in.
    """
    return graph_operation_tool.invoke({
        "resource_type": "users",
        "operation": "update",
        "resource_id": user_id,
        "body": {
            "passwordProfile": {
                "password": new_password,
                "forceChangePasswordNextSignIn": force_change_next_sign_in,
            }
        },
    })


@tool
def list_user_registered_devices_tool(user_id: str) -> str:
    """
    List devices registered by the specified user.
    """
    try:
        endpoint = f"/users/{user_id}/registeredDevices"
        result = make_graph_request("GET", endpoint)
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": {"message": str(e)}}, indent=2)


@tool
def disable_directory_device_tool(device_id: str, account_enabled: bool = False) -> str:
    """
    Enable or disable a directory device object.
    """
    try:
        endpoint = f"/devices/{device_id}"
        result = make_graph_request("PATCH", endpoint, json_data={"accountEnabled": account_enabled})
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": {"message": str(e)}}, indent=2)


@tool
def list_user_directory_roles_tool(user_id: str) -> str:
    """
    List directory roles assigned to a user.
    """
    try:
        endpoint = f"/users/{user_id}/memberOf/microsoft.graph.directoryRole"
        result = make_graph_request("GET", endpoint)
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": {"message": str(e)}}, indent=2)


@tool
def remove_user_from_directory_role_tool(role_id: str, directory_object_id: str) -> str:
    """
    Remove a directory object (user) from a directory role.
    """
    try:
        endpoint = f"/directoryRoles/{role_id}/members/{directory_object_id}/$ref"
        result = make_graph_request("DELETE", endpoint)
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": {"message": str(e)}}, indent=2)


@tool
def add_user_to_group_direct_tool(group_id: str, user_id: str) -> str:
    """
    Add a user to a group using the members/$ref endpoint.
    """
    try:
        endpoint = f"/groups/{group_id}/members/$ref"
        body = {"@odata.id": f"https://graph.microsoft.com/v1.0/directoryObjects/{user_id}"}
        result = make_graph_request("POST", endpoint, json_data=body)
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": {"message": str(e)}}, indent=2)


@tool
def remove_user_from_group_direct_tool(group_id: str, user_id: str) -> str:
    """
    Remove a user from a group.
    """
    try:
        endpoint = f"/groups/{group_id}/members/{user_id}/$ref"
        result = make_graph_request("DELETE", endpoint)
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": {"message": str(e)}}, indent=2)


# ============================================================================
# Visibility / Audit Tools
# ============================================================================


@tool
def list_sign_in_logs_tool(user_principal_name: Optional[str] = None, top: int = 50) -> str:
    """
    Retrieve sign-in logs, optionally filtered by userPrincipalName.
    """
    params: Dict[str, Any] = {"$top": min(top, 250)}
    if user_principal_name:
        params["$filter"] = f"userPrincipalName eq '{user_principal_name}'"
    try:
        result = make_graph_request("GET", "/auditLogs/signIns", params=params)
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": {"message": str(e)}}, indent=2)


@tool
def list_directory_audits_tool(top: int = 50) -> str:
    """
    Retrieve directory audit logs.
    """
    params = {"$top": min(top, 250)}
    try:
        result = make_graph_request("GET", "/auditLogs/directoryAudits", params=params)
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": {"message": str(e)}}, indent=2)


@tool
def list_risky_users_tool() -> str:
    """
    List risky users from Entra ID Protection.
    """
    try:
        result = make_graph_request("GET", "/identityProtection/riskyUsers")
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": {"message": str(e)}}, indent=2)


@tool
def list_risk_detections_tool() -> str:
    """
    List risk detections (Entra ID Protection).
    """
    try:
        result = make_graph_request("GET", "/identityProtection/riskDetections")
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": {"message": str(e)}}, indent=2)


# ============================================================================
# Application / OAuth Operations
# ============================================================================


@tool
def list_recent_applications_tool(top: int = 25) -> str:
    """
    List recently created application registrations.
    """
    params = {"$orderby": "createdDateTime desc", "$top": min(top, 100)}
    try:
        result = make_graph_request("GET", "/applications", params=params)
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": {"message": str(e)}}, indent=2)


@tool
def disable_service_principal_tool(service_principal_id: str, account_enabled: bool = False) -> str:
    """
    Enable or disable a service principal (app access).
    """
    try:
        endpoint = f"/servicePrincipals/{service_principal_id}"
        result = make_graph_request("PATCH", endpoint, json_data={"accountEnabled": account_enabled})
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": {"message": str(e)}}, indent=2)


@tool
def list_service_principals_by_appid_tool(app_id: str) -> str:
    """
    List service principals by application appId.
    """
    params = {"$filter": f"appId eq '{app_id}'"}
    try:
        result = make_graph_request("GET", "/servicePrincipals", params=params)
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": {"message": str(e)}}, indent=2)


@tool
def remove_application_password_tool(application_id: str, key_id: str) -> str:
    """
    Remove a password credential from an application registration.
    """
    try:
        endpoint = f"/applications/{application_id}/removePassword"
        body = {"keyId": key_id}
        result = make_graph_request("POST", endpoint, json_data=body)
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": {"message": str(e)}}, indent=2)


@tool
def list_oauth_permission_grants_tool(service_principal_id: Optional[str] = None) -> str:
    """
    List OAuth delegated permission grants, optionally filtered by service principal.
    """
    params = {}
    if service_principal_id:
        params["$filter"] = f"clientId eq '{service_principal_id}'"
    try:
        result = make_graph_request("GET", "/oauth2PermissionGrants", params=params if params else None)
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": {"message": str(e)}}, indent=2)


@tool
def delete_oauth_permission_grant_tool(grant_id: str) -> str:
    """
    Delete a delegated permission grant.
    """
    try:
        endpoint = f"/oauth2PermissionGrants/{grant_id}"
        result = make_graph_request("DELETE", endpoint)
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": {"message": str(e)}}, indent=2)


# ============================================================================
# Intune Managed Device Operations
# ============================================================================


@tool
def list_managed_devices_for_user_tool(user_id: str) -> str:
    """
    List Intune managed devices for a user.
    """
    params = {"$filter": f"userId eq '{user_id}'"}
    try:
        result = make_graph_request("GET", "/deviceManagement/managedDevices", params=params)
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": {"message": str(e)}}, indent=2)


@tool
def get_managed_device_tool(managed_device_id: str) -> str:
    """
    Get a specific managed device.
    """
    try:
        endpoint = f"/deviceManagement/managedDevices/{managed_device_id}"
        result = make_graph_request("GET", endpoint)
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": {"message": str(e)}}, indent=2)


def _simple_device_action(managed_device_id: str, action: str, method: str = "POST", body: Optional[dict] = None):
    endpoint = f"/deviceManagement/managedDevices/{managed_device_id}/{action}"
    return make_graph_request(method, endpoint, json_data=body or {})


@tool
def remote_lock_managed_device_tool(managed_device_id: str) -> str:
    """
    Trigger remote lock on a managed device.
    """
    try:
        result = _simple_device_action(managed_device_id, "remoteLock")
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": {"message": str(e)}}, indent=2)


@tool
def wipe_managed_device_tool(
    managed_device_id: str,
    keep_enrollment_data: bool = False,
    keep_user_data: bool = False,
    use_protected_wipe: bool = False,
) -> str:
    """
    Wipe (factory reset) a managed device.
    """
    body = {
        "keepEnrollmentData": keep_enrollment_data,
        "keepUserData": keep_user_data,
        "useProtectedWipe": use_protected_wipe,
    }
    try:
        result = _simple_device_action(managed_device_id, "wipe", body=body)
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": {"message": str(e)}}, indent=2)


@tool
def retire_managed_device_tool(managed_device_id: str) -> str:
    """
    Retire a managed device (remove corporate data).
    """
    try:
        result = _simple_device_action(managed_device_id, "retire")
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": {"message": str(e)}}, indent=2)


@tool
def delete_managed_device_record_tool(managed_device_id: str) -> str:
    """
    Delete a managed device record.
    """
    try:
        endpoint = f"/deviceManagement/managedDevices/{managed_device_id}"
        result = make_graph_request("DELETE", endpoint)
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": {"message": str(e)}}, indent=2)


@tool
def sync_managed_device_tool(managed_device_id: str) -> str:
    """
    Force policy sync on a managed device.
    """
    try:
        result = _simple_device_action(managed_device_id, "syncDevice")
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": {"message": str(e)}}, indent=2)


@tool
def rename_managed_device_tool(managed_device_id: str, device_name: str) -> str:
    """
    Rename a managed device.
    """
    try:
        body = {"deviceName": device_name}
        result = _simple_device_action(managed_device_id, "setDeviceName", body=body)
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": {"message": str(e)}}, indent=2)


@tool
def disable_lost_mode_tool(managed_device_id: str) -> str:
    """
    Disable lost mode on a managed device.
    """
    try:
        result = _simple_device_action(managed_device_id, "disableLostMode")
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": {"message": str(e)}}, indent=2)


# ============================================================================
# Intune Compliance / Configuration Visibility
# ============================================================================


@tool
def list_device_compliance_policies_tool() -> str:
    """
    List all Intune device compliance policies.
    """
    try:
        result = make_graph_request("GET", "/deviceManagement/deviceCompliancePolicies")
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": {"message": str(e)}}, indent=2)


@tool
def get_device_compliance_state_summary_tool() -> str:
    """
    Retrieve the device compliance policy state summary.
    """
    try:
        result = make_graph_request("GET", "/deviceManagement/deviceCompliancePolicyDeviceStateSummary")
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": {"message": str(e)}}, indent=2)


@tool
def list_device_configurations_tool() -> str:
    """
    List Intune device configuration profiles.
    """
    try:
        result = make_graph_request("GET", "/deviceManagement/deviceConfigurations")
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": {"message": str(e)}}, indent=2)


# ============================================================================
# Mail / Inbox Operations
# ============================================================================


@tool
def list_inbox_rules_tool(user_id: str) -> str:
    """
    List inbox message rules for a user.
    """
    try:
        endpoint = f"/users/{user_id}/mailFolders/inbox/messageRules"
        result = make_graph_request("GET", endpoint)
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": {"message": str(e)}}, indent=2)


@tool
def delete_inbox_rule_tool(user_id: str, rule_id: str) -> str:
    """
    Delete a mailbox inbox rule.
    """
    try:
        endpoint = f"/users/{user_id}/mailFolders/inbox/messageRules/{rule_id}"
        result = make_graph_request("DELETE", endpoint)
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": {"message": str(e)}}, indent=2)


@tool
def search_user_messages_tool(user_id: str, search_query: str, top: int = 25) -> str:
    """
    Perform a search over a user's mailbox.
    """
    params = {"$search": search_query, "$top": min(top, 50)}
    headers = {"ConsistencyLevel": "eventual"}
    try:
        access_token = get_access_token()
        url = f"https://graph.microsoft.com/v1.0/users/{user_id}/messages"
        with httpx.Client() as client:
            response = client.request(
                method="GET",
                url=url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                    **headers,
                },
                params=params,
                timeout=30.0,
            )
        if response.status_code == 204:
            return json.dumps({"success": True}, indent=2)
        try:
            return json.dumps(response.json(), indent=2, default=str)
        except json.JSONDecodeError:
            return json.dumps({"error": {"message": f"Invalid JSON response: {response.text}"}}, indent=2)
    except Exception as e:
        return json.dumps({"error": {"message": str(e)}}, indent=2)




# ============================================================================
# Group Operations
# ============================================================================

@tool
def list_groups_tool(select_fields: Optional[List[str]] = None, filter_expression: Optional[str] = None, top: Optional[int] = None) -> str:
    """
    List all groups in the organization.
    
    Args:
        select_fields: Optional list of fields to select
        filter_expression: Optional OData filter expression
        top: Optional maximum number of results to return
    
    Returns:
        str: JSON string containing list of groups or error information
    """
    params = {}
    if select_fields:
        params["$select"] = ",".join(select_fields)
    if filter_expression:
        params["$filter"] = filter_expression
    if top:
        params["$top"] = top
    
    return graph_operation_tool.invoke({
        "resource_type": "groups",
        "operation": "list",
        "query_params": params if params else None,
    })


@tool
def get_group_tool(group_id: str, select_fields: Optional[List[str]] = None) -> str:
    """
    Get a specific group by ID.
    
    Args:
        group_id: The ID of the group
        select_fields: Optional list of fields to select
    
    Returns:
        str: JSON string containing the group data or error information
    """
    params = {}
    if select_fields:
        params["$select"] = ",".join(select_fields)
    
    return graph_operation_tool.invoke({
        "resource_type": "groups",
        "operation": "get",
        "resource_id": group_id,
        "query_params": params if params else None,
    })


@tool
def create_group_tool(group_data: Dict[str, Any]) -> str:
    """
    Create a new group.
    
    Args:
        group_data: Dictionary containing group properties (e.g., {"displayName": "IT Team", "mailEnabled": false, "securityEnabled": true, "mailNickname": "itteam"})
    
    Returns:
        str: JSON string containing the created group or error information
    """
    return graph_operation_tool.invoke({
        "resource_type": "groups",
        "operation": "create",
        "body": group_data,
    })


@tool
def update_group_tool(group_id: str, update_data: Dict[str, Any]) -> str:
    """
    Update properties of an existing group.
    
    Args:
        group_id: The ID of the group to update
        update_data: Dictionary containing fields to update (e.g., {"displayName": "New Name", "description": "Updated description"})
    
    Returns:
        str: JSON string containing the updated group or error information
    """
    return graph_operation_tool.invoke({
        "resource_type": "groups",
        "operation": "update",
        "resource_id": group_id,
        "body": update_data,
    })


@tool
def delete_group_tool(group_id: str) -> str:
    """
    Delete a group.
    
    Args:
        group_id: The ID of the group to delete
    
    Returns:
        str: JSON string containing success message or error information
    """
    return graph_operation_tool.invoke({
        "resource_type": "groups",
        "operation": "delete",
        "resource_id": group_id,
    })


@tool
def add_group_member_tool(group_id: str, member_id: str) -> str:
    """
    Add a member (user or group) to a group.
    
    Args:
        group_id: The ID of the group
        member_id: The ID of the user or group to add as a member
    
    Returns:
        str: JSON string containing success message or error information
    """
    return graph_operation_tool.invoke({
        "resource_type": "groups",
        "operation": "addMember",
        "resource_id": group_id,
        "body": {
            "@odata.id": f"https://graph.microsoft.com/v1.0/directoryObjects/{member_id}",
        },
    })


@tool
def remove_group_member_tool(group_id: str, member_id: str) -> str:
    """
    Remove a member from a group.
    
    Args:
        group_id: The ID of the group
        member_id: The ID of the member to remove
    
    Returns:
        str: JSON string containing success message or error information
    """
    try:
        endpoint = f"/groups/{group_id}/members/{member_id}/$ref"
        result = make_graph_request("DELETE", endpoint)
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": {"message": str(e)}}, indent=2)


@tool
def add_group_owner_tool(group_id: str, owner_id: str) -> str:
    """
    Add an owner to a group.
    
    Args:
        group_id: The ID of the group
        owner_id: The ID of the user or service principal to add as an owner
    
    Returns:
        str: JSON string containing success message or error information
    """
    return graph_operation_tool.invoke({
        "resource_type": "groups",
        "operation": "addOwner",
        "resource_id": group_id,
        "body": {
            "@odata.id": f"https://graph.microsoft.com/v1.0/directoryObjects/{owner_id}",
        },
    })


@tool
def remove_group_owner_tool(group_id: str, owner_id: str) -> str:
    """
    Remove an owner from a group.
    
    Args:
        group_id: The ID of the group
        owner_id: The ID of the owner to remove
    
    Returns:
        str: JSON string containing success message or error information
    """
    try:
        endpoint = f"/groups/{group_id}/owners/{owner_id}/$ref"
        result = make_graph_request("DELETE", endpoint)
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": {"message": str(e)}}, indent=2)


@tool
def list_group_members_tool(group_id: str, select_fields: Optional[List[str]] = None, top: Optional[int] = None) -> str:
    """
    List all members of a group.
    
    Args:
        group_id: The ID of the group
        select_fields: Optional list of fields to select
        top: Optional maximum number of results to return
    
    Returns:
        str: JSON string containing list of members or error information
    """
    params = {}
    if select_fields:
        params["$select"] = ",".join(select_fields)
    if top:
        params["$top"] = top
    
    return graph_operation_tool.invoke({
        "resource_type": "groups",
        "operation": "listMembers",
        "resource_id": group_id,
        "query_params": params if params else None,
    })


@tool
def list_group_owners_tool(group_id: str, select_fields: Optional[List[str]] = None, top: Optional[int] = None) -> str:
    """
    List all owners of a group.
    
    Args:
        group_id: The ID of the group
        select_fields: Optional list of fields to select
        top: Optional maximum number of results to return
    
    Returns:
        str: JSON string containing list of owners or error information
    """
    params = {}
    if select_fields:
        params["$select"] = ",".join(select_fields)
    if top:
        params["$top"] = top
    
    return graph_operation_tool.invoke({
        "resource_type": "groups",
        "operation": "listOwners",
        "resource_id": group_id,
        "query_params": params if params else None,
    })


# ============================================================================
# Application Operations
# ============================================================================

@tool
def list_applications_tool(select_fields: Optional[List[str]] = None, filter_expression: Optional[str] = None, top: Optional[int] = None) -> str:
    """
    List all applications.
    
    Args:
        select_fields: Optional list of fields to select
        filter_expression: Optional OData filter expression
        top: Optional maximum number of results to return
    
    Returns:
        str: JSON string containing list of applications or error information
    """
    params = {}
    if select_fields:
        params["$select"] = ",".join(select_fields)
    if filter_expression:
        params["$filter"] = filter_expression
    if top:
        params["$top"] = top
    
    return graph_operation_tool.invoke({
        "resource_type": "applications",
        "operation": "list",
        "query_params": params if params else None,
    })


@tool
def get_application_tool(application_id: str, select_fields: Optional[List[str]] = None) -> str:
    """
    Get a specific application by ID.
    
    Args:
        application_id: The ID of the application
        select_fields: Optional list of fields to select
    
    Returns:
        str: JSON string containing the application data or error information
    """
    params = {}
    if select_fields:
        params["$select"] = ",".join(select_fields)
    
    return graph_operation_tool.invoke({
        "resource_type": "applications",
        "operation": "get",
        "resource_id": application_id,
        "query_params": params if params else None,
    })


@tool
def create_application_tool(application_data: Dict[str, Any]) -> str:
    """
    Create a new application.
    
    Args:
        application_data: Dictionary containing application properties (e.g., {"displayName": "My App", "web": {...}, "spa": {...}})
    
    Returns:
        str: JSON string containing the created application or error information
    """
    return graph_operation_tool.invoke({
        "resource_type": "applications",
        "operation": "create",
        "body": application_data,
    })


@tool
def update_application_tool(application_id: str, update_data: Dict[str, Any]) -> str:
    """
    Update an application.
    
    Args:
        application_id: The ID of the application to update
        update_data: Dictionary containing fields to update (e.g., {"displayName": "New Name", "web": {...}})
    
    Returns:
        str: JSON string containing the updated application or error information
    """
    return graph_operation_tool.invoke({
        "resource_type": "applications",
        "operation": "update",
        "resource_id": application_id,
        "body": update_data,
    })


@tool
def delete_application_tool(application_id: str) -> str:
    """
    Delete an application.
    
    Args:
        application_id: The ID of the application to delete
    
    Returns:
        str: JSON string containing success message or error information
    """
    return graph_operation_tool.invoke({
        "resource_type": "applications",
        "operation": "delete",
        "resource_id": application_id,
    })


# ============================================================================
# Device Operations
# ============================================================================

@tool
def list_devices_tool(select_fields: Optional[List[str]] = None, filter_expression: Optional[str] = None, top: Optional[int] = None) -> str:
    """
    List all devices.
    
    Args:
        select_fields: Optional list of fields to select
        filter_expression: Optional OData filter expression
        top: Optional maximum number of results to return
    
    Returns:
        str: JSON string containing list of devices or error information
    """
    params = {}
    if select_fields:
        params["$select"] = ",".join(select_fields)
    if filter_expression:
        params["$filter"] = filter_expression
    if top:
        params["$top"] = top
    
    return graph_operation_tool.invoke({
        "resource_type": "devices",
        "operation": "list",
        "query_params": params if params else None,
    })


@tool
def get_device_tool(device_id: str, select_fields: Optional[List[str]] = None) -> str:
    """
    Get a specific device by ID.
    
    Args:
        device_id: The ID of the device
        select_fields: Optional list of fields to select
    
    Returns:
        str: JSON string containing the device data or error information
    """
    params = {}
    if select_fields:
        params["$select"] = ",".join(select_fields)
    
    return graph_operation_tool.invoke({
        "resource_type": "devices",
        "operation": "get",
        "resource_id": device_id,
        "query_params": params if params else None,
    })


@tool
def delete_device_tool(device_id: str) -> str:
    """
    Delete a device.
    
    Args:
        device_id: The ID of the device to delete
    
    Returns:
        str: JSON string containing success message or error information
    """
    return graph_operation_tool.invoke({
        "resource_type": "devices",
        "operation": "delete",
        "resource_id": device_id,
    })


# ============================================================================
# Security Operations
# ============================================================================

@tool
def list_security_alerts_tool(select_fields: Optional[List[str]] = None, filter_expression: Optional[str] = None, top: Optional[int] = None) -> str:
    """
    List security alerts.
    
    Args:
        select_fields: Optional list of fields to select
        filter_expression: Optional OData filter expression
        top: Optional maximum number of results to return
    
    Returns:
        str: JSON string containing list of security alerts or error information
    """
    params = {}
    if select_fields:
        params["$select"] = ",".join(select_fields)
    if filter_expression:
        params["$filter"] = filter_expression
    if top:
        params["$top"] = top
    
    try:
        endpoint = "/security/alerts_v2"
        result = make_graph_request("GET", endpoint, params=params if params else None)
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": {"message": str(e)}}, indent=2)


@tool
def get_security_alert_tool(alert_id: str, select_fields: Optional[List[str]] = None) -> str:
    """
    Get a specific security alert.
    
    Args:
        alert_id: The ID of the alert
        select_fields: Optional list of fields to select
    
    Returns:
        str: JSON string containing the alert data or error information
    """
    params = {}
    if select_fields:
        params["$select"] = ",".join(select_fields)
    
    try:
        endpoint = f"/security/alerts_v2/{alert_id}"
        result = make_graph_request("GET", endpoint, params=params if params else None)
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": {"message": str(e)}}, indent=2)


@tool
def list_security_incidents_tool(select_fields: Optional[List[str]] = None, filter_expression: Optional[str] = None, top: Optional[int] = None) -> str:
    """
    List security incidents.
    
    Args:
        select_fields: Optional list of fields to select
        filter_expression: Optional OData filter expression
        top: Optional maximum number of results to return
    
    Returns:
        str: JSON string containing list of security incidents or error information
    """
    params = {}
    if select_fields:
        params["$select"] = ",".join(select_fields)
    if filter_expression:
        params["$filter"] = filter_expression
    if top:
        params["$top"] = top
    
    try:
        endpoint = "/security/incidents"
        result = make_graph_request("GET", endpoint, params=params if params else None)
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": {"message": str(e)}}, indent=2)


@tool
def get_security_incident_tool(incident_id: str, select_fields: Optional[List[str]] = None) -> str:
    """
    Get a specific security incident.
    
    Args:
        incident_id: The ID of the incident
        select_fields: Optional list of fields to select
    
    Returns:
        str: JSON string containing the incident data or error information
    """
    params = {}
    if select_fields:
        params["$select"] = ",".join(select_fields)
    
    try:
        endpoint = f"/security/incidents/{incident_id}"
        result = make_graph_request("GET", endpoint, params=params if params else None)
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": {"message": str(e)}}, indent=2)


# ============================================================================
# Attack Simulation Operations
# ============================================================================

@tool
def list_attack_simulations_tool(select_fields: Optional[List[str]] = None, filter_expression: Optional[str] = None, top: Optional[int] = None) -> str:
    """
    List attack simulation simulations.
    
    Args:
        select_fields: Optional list of fields to select
        filter_expression: Optional OData filter expression
        top: Optional maximum number of results to return (max 50 for security endpoints)
    
    Returns:
        str: JSON string containing list of simulations or error information
    """
    params = {}
    if select_fields:
        params["$select"] = ",".join(select_fields)
    if filter_expression:
        params["$filter"] = filter_expression
    if top:
        params["$top"] = min(top, 50)  # Security endpoints max at 50
    
    return graph_operation_tool.invoke({
        "resource_type": "attackSimulation",
        "operation": "listSimulations",
        "query_params": params if params else None,
        "api_version": "beta",
    })


@tool
def get_attack_simulation_tool(simulation_id: str, select_fields: Optional[List[str]] = None) -> str:
    """
    Get a specific attack simulation.
    
    Args:
        simulation_id: The ID of the simulation
        select_fields: Optional list of fields to select
    
    Returns:
        str: JSON string containing the simulation data or error information
    """
    params = {}
    if select_fields:
        params["$select"] = ",".join(select_fields)
    
    return graph_operation_tool.invoke({
        "resource_type": "attackSimulation",
        "operation": "getSimulation",
        "resource_id": simulation_id,
        "query_params": params if params else None,
        "api_version": "beta",
    })


@tool
def create_attack_simulation_tool(simulation_data: Dict[str, Any]) -> str:
    """
    Create a new attack simulation.
    
    Args:
        simulation_data: Dictionary containing simulation properties (e.g., {"displayName": "Phishing Test", "description": "...", "payload": {...}})
    
    Returns:
        str: JSON string containing the created simulation or error information
    """
    return graph_operation_tool.invoke({
        "resource_type": "attackSimulation",
        "operation": "createSimulation",
        "body": simulation_data,
        "api_version": "beta",
    })


@tool
def update_attack_simulation_tool(simulation_id: str, update_data: Dict[str, Any]) -> str:
    """
    Update an attack simulation.
    
    Args:
        simulation_id: The ID of the simulation to update
        update_data: Dictionary containing fields to update (e.g., {"displayName": "Updated Name", "status": "scheduled"})
    
    Returns:
        str: JSON string containing the updated simulation or error information
    """
    return graph_operation_tool.invoke({
        "resource_type": "attackSimulation",
        "operation": "updateSimulation",
        "resource_id": simulation_id,
        "body": update_data,
        "api_version": "beta",
    })


@tool
def delete_attack_simulation_tool(simulation_id: str) -> str:
    """
    Delete an attack simulation.
    
    Args:
        simulation_id: The ID of the simulation to delete
    
    Returns:
        str: JSON string containing success message or error information
    """
    return graph_operation_tool.invoke({
        "resource_type": "attackSimulation",
        "operation": "deleteSimulation",
        "resource_id": simulation_id,
        "api_version": "beta",
    })


@tool
def get_simulation_payload_tool(simulation_id: str, select_fields: Optional[List[str]] = None) -> str:
    """
    Get payload for a simulation.
    
    Args:
        simulation_id: The ID of the simulation
        select_fields: Optional list of fields to select
    
    Returns:
        str: JSON string containing the payload data or error information
    """
    params = {}
    if select_fields:
        params["$select"] = ",".join(select_fields)
    
    return graph_operation_tool.invoke({
        "resource_type": "attackSimulation",
        "operation": "getPayload",
        "resource_id": simulation_id,
        "query_params": params if params else None,
        "api_version": "beta",
    })


@tool
def get_simulation_login_page_tool(simulation_id: str, select_fields: Optional[List[str]] = None) -> str:
    """
    Get login page for a simulation.
    
    Args:
        simulation_id: The ID of the simulation
        select_fields: Optional list of fields to select
    
    Returns:
        str: JSON string containing the login page data or error information
    """
    params = {}
    if select_fields:
        params["$select"] = ",".join(select_fields)
    
    return graph_operation_tool.invoke({
        "resource_type": "attackSimulation",
        "operation": "getLoginPage",
        "resource_id": simulation_id,
        "query_params": params if params else None,
        "api_version": "beta",
    })


@tool
def get_simulation_landing_page_tool(simulation_id: str, select_fields: Optional[List[str]] = None) -> str:
    """
    Get landing page for a simulation.
    
    Args:
        simulation_id: The ID of the simulation
        select_fields: Optional list of fields to select
    
    Returns:
        str: JSON string containing the landing page data or error information
    """
    params = {}
    if select_fields:
        params["$select"] = ",".join(select_fields)
    
    return graph_operation_tool.invoke({
        "resource_type": "attackSimulation",
        "operation": "getLandingPage",
        "resource_id": simulation_id,
        "query_params": params if params else None,
        "api_version": "beta",
    })


# ============================================================================
# eDiscovery Operations
# ============================================================================

@tool
def list_ediscovery_cases_tool(select_fields: Optional[List[str]] = None, filter_expression: Optional[str] = None, top: Optional[int] = None) -> str:
    """
    List eDiscovery cases.
    
    Args:
        select_fields: Optional list of fields to select
        filter_expression: Optional OData filter expression
        top: Optional maximum number of results to return
    
    Returns:
        str: JSON string containing list of eDiscovery cases or error information
    """
    params = {}
    if select_fields:
        params["$select"] = ",".join(select_fields)
    if filter_expression:
        params["$filter"] = filter_expression
    if top:
        params["$top"] = top
    
    return graph_operation_tool.invoke({
        "resource_type": "ediscovery",
        "operation": "listCases",
        "query_params": params if params else None,
    })


@tool
def get_ediscovery_case_tool(case_id: str, select_fields: Optional[List[str]] = None) -> str:
    """
    Get a specific eDiscovery case.
    
    Args:
        case_id: The ID of the eDiscovery case
        select_fields: Optional list of fields to select
    
    Returns:
        str: JSON string containing the case data or error information
    """
    params = {}
    if select_fields:
        params["$select"] = ",".join(select_fields)
    
    return graph_operation_tool.invoke({
        "resource_type": "ediscovery",
        "operation": "getCase",
        "resource_id": case_id,
        "query_params": params if params else None,
    })


@tool
def create_ediscovery_case_tool(case_data: Dict[str, Any]) -> str:
    """
    Create a new eDiscovery case.
    
    Args:
        case_data: Dictionary containing case properties (e.g., {"displayName": "Case Name", "description": "..."})
    
    Returns:
        str: JSON string containing the created case or error information
    """
    return graph_operation_tool.invoke({
        "resource_type": "ediscovery",
        "operation": "createCase",
        "body": case_data,
    })


@tool
def update_ediscovery_case_tool(case_id: str, update_data: Dict[str, Any]) -> str:
    """
    Update an eDiscovery case.
    
    Args:
        case_id: The ID of the case to update
        update_data: Dictionary containing fields to update (e.g., {"displayName": "New Name", "status": "active"})
    
    Returns:
        str: JSON string containing the updated case or error information
    """
    return graph_operation_tool.invoke({
        "resource_type": "ediscovery",
        "operation": "updateCase",
        "resource_id": case_id,
        "body": update_data,
    })


@tool
def delete_ediscovery_case_tool(case_id: str) -> str:
    """
    Delete an eDiscovery case.
    
    Args:
        case_id: The ID of the case to delete
    
    Returns:
        str: JSON string containing success message or error information
    """
    return graph_operation_tool.invoke({
        "resource_type": "ediscovery",
        "operation": "deleteCase",
        "resource_id": case_id,
    })


# ============================================================================
# Secure Score Operations
# ============================================================================

@tool
def list_secure_scores_tool(select_fields: Optional[List[str]] = None, filter_expression: Optional[str] = None, top: Optional[int] = None) -> str:
    """
    List secure scores.
    
    Args:
        select_fields: Optional list of fields to select
        filter_expression: Optional OData filter expression
        top: Optional maximum number of results to return (max 50 for security endpoints)
    
    Returns:
        str: JSON string containing list of secure scores or error information
    """
    params = {}
    if select_fields:
        params["$select"] = ",".join(select_fields)
    if filter_expression:
        params["$filter"] = filter_expression
    if top:
        params["$top"] = min(top, 50)  # Security endpoints max at 50
    
    return graph_operation_tool.invoke({
        "resource_type": "secureScore",
        "operation": "listSecureScores",
        "query_params": params if params else None,
    })


@tool
def list_secure_score_control_profiles_tool(select_fields: Optional[List[str]] = None, filter_expression: Optional[str] = None, top: Optional[int] = None) -> str:
    """
    List secure score control profiles.
    
    Args:
        select_fields: Optional list of fields to select
        filter_expression: Optional OData filter expression
        top: Optional maximum number of results to return (max 50 for security endpoints)
    
    Returns:
        str: JSON string containing list of secure score control profiles or error information
    """
    params = {}
    if select_fields:
        params["$select"] = ",".join(select_fields)
    if filter_expression:
        params["$filter"] = filter_expression
    if top:
        params["$top"] = min(top, 50)  # Security endpoints max at 50
    
    try:
        endpoint = "/security/secureScoreControlProfiles"
        result = make_graph_request("GET", endpoint, params=params if params else None)
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": {"message": str(e)}}, indent=2)


# ============================================================================
# Threat Intelligence Operations
# ============================================================================

@tool
def list_threat_intelligence_indicators_tool(select_fields: Optional[List[str]] = None, filter_expression: Optional[str] = None, top: Optional[int] = None) -> str:
    """
    List threat intelligence indicators.
    
    Args:
        select_fields: Optional list of fields to select
        filter_expression: Optional OData filter expression
        top: Optional maximum number of results to return
    
    Returns:
        str: JSON string containing list of threat intelligence indicators or error information
    """
    params = {}
    if select_fields:
        params["$select"] = ",".join(select_fields)
    if filter_expression:
        params["$filter"] = filter_expression
    if top:
        params["$top"] = top
    
    return graph_operation_tool.invoke({
        "resource_type": "threatIntelligence",
        "operation": "listIndicators",
        "query_params": params if params else None,
        "api_version": "beta",
    })


@tool
def get_threat_intelligence_indicator_tool(indicator_id: str, select_fields: Optional[List[str]] = None) -> str:
    """
    Get a specific threat intelligence indicator.
    
    Args:
        indicator_id: The ID of the indicator
        select_fields: Optional list of fields to select
    
    Returns:
        str: JSON string containing the indicator data or error information
    """
    params = {}
    if select_fields:
        params["$select"] = ",".join(select_fields)
    
    return graph_operation_tool.invoke({
        "resource_type": "threatIntelligence",
        "operation": "getIndicator",
        "resource_id": indicator_id,
        "query_params": params if params else None,
        "api_version": "beta",
    })


@tool
def create_threat_intelligence_indicator_tool(indicator_data: Dict[str, Any]) -> str:
    """
    Create a new threat intelligence indicator.
    
    Args:
        indicator_data: Dictionary containing indicator properties (e.g., {"targetProduct": "Microsoft Defender", "indicator": {...}})
    
    Returns:
        str: JSON string containing the created indicator or error information
    """
    return graph_operation_tool.invoke({
        "resource_type": "threatIntelligence",
        "operation": "createIndicator",
        "body": indicator_data,
        "api_version": "beta",
    })


@tool
def update_threat_intelligence_indicator_tool(indicator_id: str, update_data: Dict[str, Any]) -> str:
    """
    Update a threat intelligence indicator.
    
    Args:
        indicator_id: The ID of the indicator to update
        update_data: Dictionary containing fields to update (e.g., {"action": "block", "expirationDateTime": "..."})
    
    Returns:
        str: JSON string containing the updated indicator or error information
    """
    return graph_operation_tool.invoke({
        "resource_type": "threatIntelligence",
        "operation": "updateIndicator",
        "resource_id": indicator_id,
        "body": update_data,
        "api_version": "beta",
    })


@tool
def delete_threat_intelligence_indicator_tool(indicator_id: str) -> str:
    """
    Delete a threat intelligence indicator.
    
    Args:
        indicator_id: The ID of the indicator to delete
    
    Returns:
        str: JSON string containing success message or error information
    """
    return graph_operation_tool.invoke({
        "resource_type": "threatIntelligence",
        "operation": "deleteIndicator",
        "resource_id": indicator_id,
        "api_version": "beta",
    })


# ============================================================================
# Threat Submission Operations
# ============================================================================

@tool
def list_threat_submissions_tool(select_fields: Optional[List[str]] = None, filter_expression: Optional[str] = None, top: Optional[int] = None) -> str:
    """
    List threat submissions.
    
    Args:
        select_fields: Optional list of fields to select
        filter_expression: Optional OData filter expression
        top: Optional maximum number of results to return
    
    Returns:
        str: JSON string containing list of threat submissions or error information
    """
    params = {}
    if select_fields:
        params["$select"] = ",".join(select_fields)
    if filter_expression:
        params["$filter"] = filter_expression
    if top:
        params["$top"] = top
    
    return graph_operation_tool.invoke({
        "resource_type": "threatSubmission",
        "operation": "listSubmissions",
        "query_params": params if params else None,
        "api_version": "beta",
    })


@tool
def get_threat_submission_tool(submission_id: str, select_fields: Optional[List[str]] = None) -> str:
    """
    Get a specific threat submission.
    
    Args:
        submission_id: The ID of the submission
        select_fields: Optional list of fields to select
    
    Returns:
        str: JSON string containing the submission data or error information
    """
    params = {}
    if select_fields:
        params["$select"] = ",".join(select_fields)
    
    return graph_operation_tool.invoke({
        "resource_type": "threatSubmission",
        "operation": "getSubmission",
        "resource_id": submission_id,
        "query_params": params if params else None,
        "api_version": "beta",
    })


@tool
def create_threat_submission_tool(submission_data: Dict[str, Any]) -> str:
    """
    Create a new threat submission.
    
    Args:
        submission_data: Dictionary containing submission properties (e.g., {"category": "phishing", "contentType": "email", "value": "..."})
    
    Returns:
        str: JSON string containing the created submission or error information
    """
    return graph_operation_tool.invoke({
        "resource_type": "threatSubmission",
        "operation": "createSubmission",
        "body": submission_data,
        "api_version": "beta",
    })


# ============================================================================
# Identities Health Operations
# ============================================================================

@tool
def list_identities_health_issues_tool(
    select_fields: Optional[List[str]] = None,
    filter_expression: Optional[str] = None,
    top: Optional[int] = None,
) -> str:
    """
    List Microsoft Defender for Identity health issues.

    Args:
        select_fields: Optional list of fields to select
        filter_expression: Optional OData filter expression
        top: Optional maximum number of results to return (max 50)

    Returns:
        str: JSON string containing list of health issues or error information
    """
    params: Dict[str, Any] = {}
    if select_fields:
        params["$select"] = ",".join(select_fields)
    if filter_expression:
        params["$filter"] = filter_expression
    if top:
        params["$top"] = min(top, 50)

    return graph_operation_tool.invoke({
        "resource_type": "identitiesHealth",
        "operation": "listHealthIssues",
        "query_params": params if params else None,
        "api_version": "beta",
    })


@tool
def get_identities_health_issue_tool(health_issue_id: str, select_fields: Optional[List[str]] = None) -> str:
    """
    Get a specific Microsoft Defender for Identity health issue.

    Args:
        health_issue_id: The ID of the health issue
        select_fields: Optional list of fields to select

    Returns:
        str: JSON string containing the health issue or error information
    """
    params: Dict[str, Any] = {}
    if select_fields:
        params["$select"] = ",".join(select_fields)

    return graph_operation_tool.invoke({
        "resource_type": "identitiesHealth",
        "operation": "getHealthIssue",
        "resource_id": health_issue_id,
        "query_params": params if params else None,
        "api_version": "beta",
    })


@tool
def update_identities_health_issue_tool(health_issue_id: str, update_data: Dict[str, Any]) -> str:
    """
    Update a Microsoft Defender for Identity health issue.

    Args:
        health_issue_id: The ID of the health issue
        update_data: Dictionary containing fields to update (e.g., {"status": "resolved"})

    Returns:
        str: JSON string containing the updated health issue or error information
    """
    return graph_operation_tool.invoke({
        "resource_type": "identitiesHealth",
        "operation": "updateHealthIssue",
        "resource_id": health_issue_id,
        "body": update_data,
        "api_version": "beta",
    })


# ============================================================================
# Identities Sensor Operations
# ============================================================================

@tool
def list_identities_sensors_tool(
    select_fields: Optional[List[str]] = None,
    filter_expression: Optional[str] = None,
    top: Optional[int] = None,
    include_count: bool = False,
) -> str:
    """
    List Microsoft Defender for Identity sensors.

    Args:
        select_fields: Optional list of fields to select
        filter_expression: Optional OData filter expression
        top: Optional maximum number of results to return (max 50)
        include_count: Whether to include @$count in the response

    Returns:
        str: JSON string containing list of sensors or error information
    """
    params: Dict[str, Any] = {}
    if select_fields:
        params["$select"] = ",".join(select_fields)
    if filter_expression:
        params["$filter"] = filter_expression
    if top:
        params["$top"] = min(top, 50)
    if include_count:
        params["$count"] = True

    return graph_operation_tool.invoke({
        "resource_type": "identitiesSensors",
        "operation": "listSensors",
        "query_params": params if params else None,
        "api_version": "beta",
    })


@tool
def get_identities_sensor_tool(sensor_id: str, select_fields: Optional[List[str]] = None) -> str:
    """
    Get a specific Microsoft Defender for Identity sensor.

    Args:
        sensor_id: The ID of the sensor
        select_fields: Optional list of fields to select

    Returns:
        str: JSON string containing the sensor or error information
    """
    params: Dict[str, Any] = {}
    if select_fields:
        params["$select"] = ",".join(select_fields)

    return graph_operation_tool.invoke({
        "resource_type": "identitiesSensors",
        "operation": "getSensor",
        "resource_id": sensor_id,
        "query_params": params if params else None,
        "api_version": "beta",
    })


@tool
def update_identities_sensor_tool(sensor_id: str, update_data: Dict[str, Any]) -> str:
    """
    Update a Microsoft Defender for Identity sensor.

    Args:
        sensor_id: The ID of the sensor
        update_data: Dictionary containing fields to update (e.g., {"status": "active"})

    Returns:
        str: JSON string containing the updated sensor or error information
    """
    return graph_operation_tool.invoke({
        "resource_type": "identitiesSensors",
        "operation": "updateSensor",
        "resource_id": sensor_id,
        "body": update_data,
        "api_version": "beta",
    })


@tool
def delete_identities_sensor_tool(sensor_id: str) -> str:
    """
    Delete a Microsoft Defender for Identity sensor.

    Args:
        sensor_id: The ID of the sensor

    Returns:
        str: JSON string containing success or error information
    """
    return graph_operation_tool.invoke({
        "resource_type": "identitiesSensors",
        "operation": "deleteSensor",
        "resource_id": sensor_id,
        "api_version": "beta",
    })
