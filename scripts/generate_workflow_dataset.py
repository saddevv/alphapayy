#!/usr/bin/env python3
"""
Synthetic fine-tuning dataset generator for the Qwen 1.5B workflow planner.

Generates JSONL records in chat format:
  messages[0] = system (tool catalog + task description)
  messages[1] = user   (natural-language query)
  messages[2] = assistant (WorkflowPlan JSON)

Run from repo root:
  python scripts/generate_workflow_dataset.py \
      --output data/graph_workflow_ft_dataset.jsonl \
      --seed 42

The assistant turn is exactly the JSON the model must learn to produce,
matching the WorkflowPlan schema in graph_agent/workflow_plan.py.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Tool catalog — compact schema (name, required args, arg types)
# Used both in the system prompt and to validate generated records.
# ---------------------------------------------------------------------------

TOOL_CATALOG: dict[str, dict[str, Any]] = {
    # ── User operations ─────────────────────────────────────────────────────
    "get_user_tool": {
        "desc": "Get a user by ID, UPN, or email.",
        "args": {"user_id": "str"},
        "opt_args": {"select_fields": "list[str]"},
    },
    "create_user_tool": {
        "desc": "Create a new user in Azure AD.",
        "args": {"user_data": "dict"},
    },
    "update_user_tool": {
        "desc": "Update properties of an existing user.",
        "args": {"user_id": "str", "update_data": "dict"},
    },
    "delete_user_tool": {
        "desc": "Delete a user from Azure AD.",
        "args": {"user_id": "str"},
    },
    "search_user_by_upn_tool": {
        "desc": "Find a user by exact UPN/email using $filter.",
        "args": {"user_principal_name": "str"},
    },
    "set_user_account_enabled_tool": {
        "desc": "Enable or disable a user's sign-in (accountEnabled flag).",
        "args": {"user_id": "str", "account_enabled": "bool"},
    },
    "reset_user_password_tool": {
        "desc": "Admin-reset a user's password.",
        "args": {"user_id": "str", "new_password": "str"},
        "opt_args": {"force_change_next_sign_in": "bool"},
    },
    "change_user_password_tool": {
        "desc": "Change a user's password (requires current password).",
        "args": {"user_id": "str", "current_password": "str", "new_password": "str"},
    },
    "validate_user_password_tool": {
        "desc": "Validate password strength and policy compliance for a user.",
        "args": {"user_id": "str", "password": "str"},
    },
    "revoke_user_signin_sessions_tool": {
        "desc": "Revoke all sign-in sessions for a user, forcing re-authentication.",
        "args": {"user_id": "str"},
    },
    "invalidate_user_refresh_tokens_tool": {
        "desc": "Invalidate all refresh tokens issued to apps for a user.",
        "args": {"user_id": "str"},
    },
    "export_user_personal_data_tool": {
        "desc": "Export a user's personal data to a storage location.",
        "args": {"user_id": "str", "storage_location": "str"},
    },
    "retry_user_service_provisioning_tool": {
        "desc": "Retry service provisioning for a user.",
        "args": {"user_id": "str"},
    },
    "convert_external_user_to_internal_tool": {
        "desc": "Convert an external guest user to an internal member user.",
        "args": {"user_id": "str"},
    },
    "get_user_delta_tool": {
        "desc": "Get incremental changes to users (delta query).",
        "args": {},
        "opt_args": {"delta_token": "str", "select_fields": "list[str]"},
    },
    "list_user_groups_tool": {
        "desc": "List all groups the user is a member of.",
        "args": {"user_id": "str"},
    },
    "list_user_registered_devices_tool": {
        "desc": "List devices registered by the user.",
        "args": {"user_id": "str"},
    },
    "list_user_directory_roles_tool": {
        "desc": "List directory roles assigned to a user.",
        "args": {"user_id": "str"},
    },
    "remove_user_from_directory_role_tool": {
        "desc": "Remove a user from a directory role.",
        "args": {"role_id": "str", "directory_object_id": "str"},
    },
    "add_user_to_group_direct_tool": {
        "desc": "Add a user to a group (members/$ref endpoint).",
        "args": {"group_id": "str", "user_id": "str"},
    },
    "remove_user_from_group_direct_tool": {
        "desc": "Remove a user from a group.",
        "args": {"group_id": "str", "user_id": "str"},
    },
    "disable_directory_device_tool": {
        "desc": "Enable or disable a directory device object.",
        "args": {"device_id": "str"},
        "opt_args": {"account_enabled": "bool"},
    },
    # ── Group operations ─────────────────────────────────────────────────────
    "list_groups_tool": {
        "desc": "List all groups in the organization.",
        "args": {},
        "opt_args": {"select_fields": "list[str]", "filter_expression": "str", "top": "int"},
    },
    "get_group_tool": {
        "desc": "Get a specific group by ID.",
        "args": {"group_id": "str"},
        "opt_args": {"select_fields": "list[str]"},
    },
    "create_group_tool": {
        "desc": "Create a new security or Microsoft 365 group.",
        "args": {"group_data": "dict"},
    },
    "update_group_tool": {
        "desc": "Update properties of an existing group.",
        "args": {"group_id": "str", "update_data": "dict"},
    },
    "delete_group_tool": {
        "desc": "Delete a group from Azure AD.",
        "args": {"group_id": "str"},
    },
    "add_group_member_tool": {
        "desc": "Add a user or object to a group as a member.",
        "args": {"group_id": "str", "member_id": "str"},
    },
    "remove_group_member_tool": {
        "desc": "Remove a member from a group.",
        "args": {"group_id": "str", "member_id": "str"},
    },
    "add_group_owner_tool": {
        "desc": "Add an owner to a group.",
        "args": {"group_id": "str", "owner_id": "str"},
    },
    "remove_group_owner_tool": {
        "desc": "Remove an owner from a group.",
        "args": {"group_id": "str", "owner_id": "str"},
    },
    "list_group_members_tool": {
        "desc": "List all members of a group.",
        "args": {"group_id": "str"},
        "opt_args": {"select_fields": "list[str]", "top": "int"},
    },
    "list_group_owners_tool": {
        "desc": "List all owners of a group.",
        "args": {"group_id": "str"},
        "opt_args": {"select_fields": "list[str]", "top": "int"},
    },
    # ── Application operations ───────────────────────────────────────────────
    "list_applications_tool": {
        "desc": "List all application registrations.",
        "args": {},
        "opt_args": {"select_fields": "list[str]", "filter_expression": "str", "top": "int"},
    },
    "get_application_tool": {
        "desc": "Get a specific application registration by ID.",
        "args": {"application_id": "str"},
        "opt_args": {"select_fields": "list[str]"},
    },
    "create_application_tool": {
        "desc": "Create a new application registration.",
        "args": {"application_data": "dict"},
    },
    "update_application_tool": {
        "desc": "Update an application registration.",
        "args": {"application_id": "str", "update_data": "dict"},
    },
    "delete_application_tool": {
        "desc": "Delete an application registration.",
        "args": {"application_id": "str"},
    },
    # ── Device operations ────────────────────────────────────────────────────
    "list_devices_tool": {
        "desc": "List all directory device objects.",
        "args": {},
        "opt_args": {"select_fields": "list[str]", "filter_expression": "str", "top": "int"},
    },
    "get_device_tool": {
        "desc": "Get a specific device by ID.",
        "args": {"device_id": "str"},
        "opt_args": {"select_fields": "list[str]"},
    },
    "delete_device_tool": {
        "desc": "Delete a device from Azure AD.",
        "args": {"device_id": "str"},
    },
    "list_managed_devices_for_user_tool": {
        "desc": "List Intune-managed devices for a specific user.",
        "args": {"user_id": "str"},
    },
    "get_managed_device_tool": {
        "desc": "Get details of a specific Intune-managed device.",
        "args": {"managed_device_id": "str"},
    },
    "remote_lock_managed_device_tool": {
        "desc": "Remotely lock an Intune-managed device.",
        "args": {"managed_device_id": "str"},
    },
    "wipe_managed_device_tool": {
        "desc": "Factory-wipe an Intune-managed device.",
        "args": {"managed_device_id": "str"},
        "opt_args": {
            "keep_enrollment_data": "bool",
            "keep_user_data": "bool",
            "use_protected_wipe": "bool",
        },
    },
    "retire_managed_device_tool": {
        "desc": "Retire an Intune-managed device (remove corporate data).",
        "args": {"managed_device_id": "str"},
    },
    "delete_managed_device_record_tool": {
        "desc": "Delete an Intune managed device record.",
        "args": {"managed_device_id": "str"},
    },
    "sync_managed_device_tool": {
        "desc": "Force policy sync on an Intune-managed device.",
        "args": {"managed_device_id": "str"},
    },
    "rename_managed_device_tool": {
        "desc": "Rename an Intune-managed device.",
        "args": {"managed_device_id": "str", "device_name": "str"},
    },
    "disable_lost_mode_tool": {
        "desc": "Disable lost mode on an Intune-managed device.",
        "args": {"managed_device_id": "str"},
    },
    "list_device_compliance_policies_tool": {
        "desc": "List all Intune device compliance policies.",
        "args": {},
    },
    "get_device_compliance_state_summary_tool": {
        "desc": "Retrieve the device compliance policy state summary.",
        "args": {},
    },
    "list_device_configurations_tool": {
        "desc": "List Intune device configuration profiles.",
        "args": {},
    },
    # ── Security: alerts ─────────────────────────────────────────────────────
    "list_security_alerts_tool": {
        "desc": "List security alerts from /security/alerts_v2 (max $top=50).",
        "args": {},
        "opt_args": {"select_fields": "list[str]", "filter_expression": "str", "top": "int"},
    },
    "get_security_alert_tool": {
        "desc": "Get a specific security alert by ID.",
        "args": {"alert_id": "str"},
        "opt_args": {"select_fields": "list[str]"},
    },
    "update_alert_tool": {
        "desc": "Update a security alert (e.g. status, assignedTo).",
        "args": {"alert_id": "str", "update_data": "dict"},
    },
    # ── Security: incidents ──────────────────────────────────────────────────
    "list_security_incidents_tool": {
        "desc": "List security incidents.",
        "args": {},
        "opt_args": {"select_fields": "list[str]", "filter_expression": "str", "top": "int"},
    },
    "get_security_incident_tool": {
        "desc": "Get a specific security incident by ID.",
        "args": {"incident_id": "str"},
        "opt_args": {"select_fields": "list[str]"},
    },
    "update_incident_tool": {
        "desc": "Update a security incident (e.g. status, assignedTo).",
        "args": {"incident_id": "str", "update_data": "dict"},
    },
    # ── Security: secure scores ──────────────────────────────────────────────
    "list_secure_scores_tool": {
        "desc": "List historical secure scores.",
        "args": {},
        "opt_args": {"select_fields": "list[str]", "filter_expression": "str", "top": "int"},
    },
    "get_secure_score_tool": {
        "desc": "Get a specific secure score by ID.",
        "args": {"secure_score_id": "str"},
    },
    "list_secure_score_control_profiles_tool": {
        "desc": "List secure score control profiles.",
        "args": {},
        "opt_args": {"select_fields": "list[str]", "filter_expression": "str", "top": "int"},
    },
    "get_secure_score_control_profile_tool": {
        "desc": "Get a specific secure score control profile by ID.",
        "args": {"profile_id": "str"},
    },
    "update_secure_score_control_profile_tool": {
        "desc": "Update a secure score control profile.",
        "args": {"profile_id": "str", "update_data": "dict"},
    },
    # ── Security: identities health ──────────────────────────────────────────
    "list_identities_health_issues_tool": {
        "desc": "List identity health issues from Defender for Identity.",
        "args": {},
    },
    "get_identities_health_issue_tool": {
        "desc": "Get a specific identity health issue by ID.",
        "args": {"health_issue_id": "str"},
    },
    "update_identities_health_issue_tool": {
        "desc": "Update an identity health issue (e.g. mark resolved).",
        "args": {"health_issue_id": "str", "update_data": "dict"},
    },
    # ── Security: sensors ────────────────────────────────────────────────────
    "list_identities_sensors_tool": {
        "desc": "List Defender for Identity sensors.",
        "args": {},
    },
    "get_identities_sensor_tool": {
        "desc": "Get a specific sensor by ID.",
        "args": {"sensor_id": "str"},
    },
    "update_identities_sensor_tool": {
        "desc": "Update a sensor (e.g. settings).",
        "args": {"sensor_id": "str", "update_data": "dict"},
    },
    "delete_identities_sensor_tool": {
        "desc": "Delete a sensor.",
        "args": {"sensor_id": "str"},
    },
    # ── Attack simulation ────────────────────────────────────────────────────
    "list_attack_simulations_tool": {
        "desc": "List attack simulation campaigns.",
        "args": {},
        "opt_args": {"select_fields": "list[str]", "filter_expression": "str", "top": "int"},
    },
    "get_attack_simulation_tool": {
        "desc": "Get a specific attack simulation by ID.",
        "args": {"simulation_id": "str"},
        "opt_args": {"select_fields": "list[str]"},
    },
    "create_attack_simulation_tool": {
        "desc": "Create a new attack simulation campaign.",
        "args": {"simulation_data": "dict"},
    },
    "update_attack_simulation_tool": {
        "desc": "Update an attack simulation campaign.",
        "args": {"simulation_id": "str", "update_data": "dict"},
    },
    "delete_attack_simulation_tool": {
        "desc": "Delete an attack simulation campaign.",
        "args": {"simulation_id": "str"},
    },
    "get_simulation_payload_tool": {
        "desc": "Get the payload for an attack simulation.",
        "args": {"simulation_id": "str"},
        "opt_args": {"select_fields": "list[str]"},
    },
    "get_simulation_login_page_tool": {
        "desc": "Get the login page for an attack simulation.",
        "args": {"simulation_id": "str"},
        "opt_args": {"select_fields": "list[str]"},
    },
    "get_simulation_landing_page_tool": {
        "desc": "Get the landing page for an attack simulation.",
        "args": {"simulation_id": "str"},
        "opt_args": {"select_fields": "list[str]"},
    },
    # ── eDiscovery ───────────────────────────────────────────────────────────
    "list_ediscovery_cases_tool": {
        "desc": "List eDiscovery cases.",
        "args": {},
        "opt_args": {"select_fields": "list[str]", "filter_expression": "str", "top": "int"},
    },
    "get_ediscovery_case_tool": {
        "desc": "Get a specific eDiscovery case by ID.",
        "args": {"case_id": "str"},
        "opt_args": {"select_fields": "list[str]"},
    },
    "create_ediscovery_case_tool": {
        "desc": "Create a new eDiscovery case.",
        "args": {"case_data": "dict"},
    },
    "update_ediscovery_case_tool": {
        "desc": "Update an eDiscovery case.",
        "args": {"case_id": "str", "update_data": "dict"},
    },
    "delete_ediscovery_case_tool": {
        "desc": "Delete an eDiscovery case.",
        "args": {"case_id": "str"},
    },
    "get_ediscovery_case_operations_tool": {
        "desc": "List operations for a specific eDiscovery case.",
        "args": {"case_id": "str"},
    },
    # ── Threat intelligence ──────────────────────────────────────────────────
    "list_threat_intelligence_indicators_tool": {
        "desc": "List threat intelligence indicators (tiIndicators).",
        "args": {},
        "opt_args": {"select_fields": "list[str]", "filter_expression": "str", "top": "int"},
    },
    "get_threat_intelligence_indicator_tool": {
        "desc": "Get a specific threat intelligence indicator by ID.",
        "args": {"indicator_id": "str"},
    },
    "create_threat_intelligence_indicator_tool": {
        "desc": "Create a new threat intelligence indicator.",
        "args": {"indicator_data": "dict"},
    },
    "update_threat_intelligence_indicator_tool": {
        "desc": "Update a threat intelligence indicator.",
        "args": {"indicator_id": "str", "update_data": "dict"},
    },
    "delete_threat_intelligence_indicator_tool": {
        "desc": "Delete a threat intelligence indicator.",
        "args": {"indicator_id": "str"},
    },
    # ── Threat submissions ───────────────────────────────────────────────────
    "list_threat_submissions_tool": {
        "desc": "List threat submissions.",
        "args": {},
        "opt_args": {"select_fields": "list[str]", "top": "int"},
    },
    "get_threat_submission_tool": {
        "desc": "Get a specific threat submission by ID.",
        "args": {"submission_id": "str"},
    },
    "create_threat_submission_tool": {
        "desc": "Create a new threat submission (email, URL, or file).",
        "args": {"submission_data": "dict"},
    },
    # ── Visibility / audit ───────────────────────────────────────────────────
    "list_sign_in_logs_tool": {
        "desc": "Retrieve Azure AD sign-in logs.",
        "args": {},
        "opt_args": {"user_principal_name": "str", "top": "int"},
    },
    "list_directory_audits_tool": {
        "desc": "Retrieve directory audit logs.",
        "args": {},
        "opt_args": {"top": "int"},
    },
    "list_risky_users_tool": {
        "desc": "List risky users from Entra ID Protection.",
        "args": {},
    },
    "list_risk_detections_tool": {
        "desc": "List risk detections from Entra ID Protection.",
        "args": {},
    },
    # ── App / OAuth ──────────────────────────────────────────────────────────
    "list_recent_applications_tool": {
        "desc": "List recently created application registrations.",
        "args": {},
        "opt_args": {"top": "int"},
    },
    "disable_service_principal_tool": {
        "desc": "Enable or disable a service principal (app access).",
        "args": {"service_principal_id": "str"},
        "opt_args": {"account_enabled": "bool"},
    },
    "list_service_principals_by_appid_tool": {
        "desc": "List service principals matching an application appId.",
        "args": {"app_id": "str"},
    },
    "remove_application_password_tool": {
        "desc": "Remove a password credential (secret) from an application registration.",
        "args": {"application_id": "str", "key_id": "str"},
    },
    "list_oauth_permission_grants_tool": {
        "desc": "List OAuth2 delegated permission grants.",
        "args": {},
        "opt_args": {"service_principal_id": "str"},
    },
    "delete_oauth_permission_grant_tool": {
        "desc": "Delete a delegated OAuth permission grant.",
        "args": {"grant_id": "str"},
    },
    # ── Mailbox ──────────────────────────────────────────────────────────────
    "list_inbox_rules_tool": {
        "desc": "List inbox message rules for a user.",
        "args": {"user_id": "str"},
    },
    "delete_inbox_rule_tool": {
        "desc": "Delete a mailbox inbox rule.",
        "args": {"user_id": "str", "rule_id": "str"},
    },
    "search_user_messages_tool": {
        "desc": "Search a user's mailbox for messages.",
        "args": {"user_id": "str", "search_query": "str"},
        "opt_args": {"top": "int"},
    },
    # ── Generic / discovery ──────────────────────────────────────────────────
    "graph_operation_tool": {
        "desc": "Generic tool for any Graph API operation (create/update/delete/action).",
        "args": {"resource_type": "str", "operation": "str"},
        "opt_args": {
            "resource_id": "str",
            "body": "dict",
            "query_params": "dict",
            "api_version": "str",
        },
    },
    "list_resource_operations_tool": {
        "desc": "Discover available operations for a Graph resource type.",
        "args": {"resource_type": "str"},
    },
    "get_graph_resource_schema_tool": {
        "desc": "Inspect available fields for a Graph API resource.",
        "args": {"resource_name": "str"},
    },
}

# ---------------------------------------------------------------------------
# Fake-data pools
# ---------------------------------------------------------------------------

UPNS = [
    "alice.johnson@contoso.com", "bob.smith@fabrikam.com",
    "carol.white@corp.example.com", "david.lee@tailspin.com",
    "eve.martin@northwind.com", "frank.chen@woodgrove.com",
    "grace.kim@adventureworks.com", "henry.brown@litware.com",
]
DISPLAY_NAMES = [
    "Alice Johnson", "Bob Smith", "Carol White", "David Lee",
    "Eve Martin", "Frank Chen", "Grace Kim", "Henry Brown",
]
GUIDS = [
    "a1b2c3d4-e5f6-4789-abcd-ef1234567890",
    "b2c3d4e5-f6a7-4890-bcde-f12345678901",
    "c3d4e5f6-a7b8-4901-cdef-123456789012",
    "d4e5f6a7-b8c9-4012-def0-234567890123",
    "e5f6a7b8-c9d0-4123-ef01-345678901234",
    "f6a7b8c9-d0e1-4234-f012-456789012345",
    "a7b8c9d0-e1f2-4345-0123-567890123456",
    "b8c9d0e1-f2a3-4456-1234-678901234567",
]
GROUP_GUIDS = [
    "11111111-aaaa-4111-a111-aaaaaaaaaaaa",
    "22222222-bbbb-4222-b222-bbbbbbbbbbbb",
    "33333333-cccc-4333-c333-cccccccccccc",
    "44444444-dddd-4444-d444-dddddddddddd",
]
APP_GUIDS = [
    "55555555-eeee-4555-e555-eeeeeeeeeeee",
    "66666666-ffff-4666-f666-ffffffffffff",
]
DEVICE_GUIDS = [
    "77777777-1111-4777-a777-111111111111",
    "88888888-2222-4888-b888-222222222222",
]
ALERT_IDS = [
    "da637292040355219386_-880718810",
    "da637315339080326441_-2102478304",
]
INCIDENT_IDS = ["48", "92", "115", "203"]
PASSWORDS = ["P@ssw0rd2024!", "S3cur3P@ss!", "C0mpl3x#Pass"]
STORAGE_LOCATIONS = [
    "https://storageaccount.blob.core.windows.net/container",
    "https://backup.blob.core.windows.net/exports",
]
SEVERITY_FILTERS = [
    "severity eq 'high'",
    "severity eq 'medium'",
    "severity eq 'low'",
]
STATUS_FILTERS = [
    "status eq 'active'",
    "status eq 'resolved'",
    "status eq 'inProgress'",
]
ROLE_IDS = [
    "62e90394-69f5-4237-9190-012177145e10",
    "194ae4cb-b126-40b2-bd5b-6091b380977d",
]
SENSOR_IDS = [
    "sensor-11111111-1111-1111-1111-111111111111",
    "sensor-22222222-2222-2222-2222-222222222222",
]
GRANT_IDS = ["grant-aaaa", "grant-bbbb"]
RULE_IDS = ["AAAAAA==", "BBBBBB=="]
KEY_IDS = ["key-1111", "key-2222"]
CASE_IDS = ["case-aaaa-0001", "case-bbbb-0002"]
INDICATOR_IDS = ["ind-11111", "ind-22222"]
SUBMISSION_IDS = ["sub-11111", "sub-22222"]
SCORE_IDS = ["score-aaaa", "score-bbbb"]
PROFILE_IDS = ["profile-aaaa", "profile-bbbb"]
ISSUE_IDS = ["issue-aaaa", "issue-bbbb"]
SIM_IDS = ["sim-aaaa-0001", "sim-bbbb-0002"]

SEVEN_DAYS_AGO = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%dT00:00:00Z")
THIRTY_DAYS_AGO = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%dT00:00:00Z")

# ---------------------------------------------------------------------------
# System prompt (compact, fits inside 2k tokens)
# ---------------------------------------------------------------------------

_TOOL_LINES = "\n".join(
    f"- {name}: {meta['desc']}"
    for name, meta in TOOL_CATALOG.items()
)

SYSTEM_PROMPT = f"""You are a Microsoft Graph API workflow planner.

Given a user query, output a JSON WorkflowPlan and NOTHING else.

Schema:
{{
  "steps": [
    {{
      "step_id": "s1",           // unique id within plan
      "tool": "<tool_name>",     // must be from the tool list below
      "args": {{}},                // tool arguments; use literals or "$sN.field" refs
      "depends_on": [],          // step_ids that must finish first
      "description": ""          // one-line rationale (optional)
    }}
  ],
  "final_action": "execute_plan",
  "confidence": 0.95             // 0.0-1.0 self-assessment
}}

Reference rules:
- Use "$sN.field" to reference output of a prior step (e.g. "$s1.id").
- List the referenced step in depends_on.
- Referenceable fields: id, userPrincipalName, mail, groupId, appId, deviceId,
  managedDeviceId, incidentId, alertId, caseId, simulationId, principalId.

Available tools:
{_TOOL_LINES}

Output only the JSON object. No markdown, no explanation."""


# ---------------------------------------------------------------------------
# Single-step record templates
# Each tuple: (query_variants, plan_factory)
# ---------------------------------------------------------------------------

def _plan(steps: list[dict], confidence: float = 0.95) -> dict:
    return {"steps": steps, "final_action": "execute_plan", "confidence": confidence}


def _step(sid: str, tool: str, args: dict, deps: list[str] | None = None, desc: str = "") -> dict:
    return {
        "step_id": sid,
        "tool": tool,
        "args": args,
        "depends_on": deps or [],
        "description": desc,
    }


def _rng_upn(rng: random.Random) -> str:
    return rng.choice(UPNS)


def _rng_name(rng: random.Random) -> str:
    return rng.choice(DISPLAY_NAMES)


def _rng_uid(rng: random.Random) -> str:
    return rng.choice(GUIDS)


def _rng_gid(rng: random.Random) -> str:
    return rng.choice(GROUP_GUIDS)


def _rng_did(rng: random.Random) -> str:
    return rng.choice(DEVICE_GUIDS)


def _rng_aid(rng: random.Random) -> str:
    return rng.choice(ALERT_IDS)


def _rng_iid(rng: random.Random) -> str:
    return rng.choice(INCIDENT_IDS)


def _rng_pwd(rng: random.Random) -> str:
    return rng.choice(PASSWORDS)


_QUERY_PREFIXES = [
    "",
    "Please ",
    "Can you ",
    "Could you ",
    "I need you to ",
    "Help me ",
]
_QUERY_SUFFIXES = [
    "",
    " for this tenant",
    " as soon as possible",
    " today",
    " right now",
]
_TRAILING_PUNCT = re.compile(r"[!?.,;:]+$")


def _normalize_query(query: str) -> str:
    compact = " ".join(query.lower().strip().split())
    compact = _TRAILING_PUNCT.sub("", compact)
    return compact


def _style_query(base_query: str, rng: random.Random) -> str:
    """Light query diversification while keeping intent unchanged."""
    body = base_query.strip()
    if not body:
        return body
    lowered = body[0].lower() + body[1:]
    prefix = rng.choice(_QUERY_PREFIXES)
    suffix = rng.choice(_QUERY_SUFFIXES)
    if prefix:
        body = f"{prefix}{lowered}"
    body = f"{body}{suffix}".strip()
    if prefix in {"Can you ", "Could you "}:
        body = f"{body}?"
    return body


def _difficulty_for_plan(plan: dict[str, Any]) -> str:
    if plan.get("final_action") == "clarify":
        return "hard"
    step_count = len(plan.get("steps", []))
    if step_count <= 1:
        return "easy"
    if step_count <= 3:
        return "medium"
    return "hard"


def _split_for_query(query: str) -> str:
    digest = hashlib.sha256(_normalize_query(query).encode("utf-8")).hexdigest()
    bucket = int(digest[:8], 16) % 10
    return "validation" if bucket == 0 else "train"


def _clarify_plan(reason: str, confidence: float = 0.45) -> dict[str, Any]:
    _ = reason
    return {
        "steps": [],
        "final_action": "clarify",
        "confidence": confidence,
    }


def build_clarify_templates(rng: random.Random) -> list[tuple[list[str], dict[str, Any]]]:
    return [
        (
            [
                "Disable this user account",
                "Block this user right away",
            ],
            _clarify_plan("Missing user identifier (UPN or user ID).", confidence=0.4),
        ),
        (
            [
                "Resolve the incident now",
                "Close that security incident",
            ],
            _clarify_plan("Missing incident identifier.", confidence=0.42),
        ),
        (
            [
                "Update secure score control profile status",
                "Set control profile to thirdParty",
            ],
            _clarify_plan("Missing control profile identifier.", confidence=0.43),
        ),
        (
            [
                "Delete inbox rule for user",
                "Remove that mailbox rule",
            ],
            _clarify_plan("Missing user identifier and/or inbox rule ID.", confidence=0.41),
        ),
        (
            [
                "Wipe a managed device",
                "Remote wipe device immediately",
            ],
            _clarify_plan("Missing managed device identifier.", confidence=0.39),
        ),
    ]


# ---------------------------------------------------------------------------
# Template definitions:  list of (queries, plan_fn)
# ---------------------------------------------------------------------------

def build_templates(rng: random.Random) -> list[tuple[list[str], dict]]:
    uid = _rng_uid(rng)
    upn = _rng_upn(rng)
    name = _rng_name(rng)
    gid = _rng_gid(rng)
    did = _rng_did(rng)
    aid = _rng_aid(rng)
    iid = _rng_iid(rng)
    pwd = _rng_pwd(rng)
    new_pwd = _rng_pwd(rng)
    app_id = rng.choice(APP_GUIDS)
    storage = rng.choice(STORAGE_LOCATIONS)
    sev_filter = rng.choice(SEVERITY_FILTERS)
    status_filter = rng.choice(STATUS_FILTERS)

    templates: list[tuple[list[str], dict]] = []

    # ── get_user_tool ────────────────────────────────────────────────────────
    templates.append((
        [
            f"Get details for user {upn}",
            f"Show me the profile of {upn}",
            f"Fetch user information for {uid}",
            f"Look up user {name}",
        ],
        _plan([_step("s1", "get_user_tool", {"user_id": upn}, desc="Fetch user profile")]),
    ))

    # ── search_user_by_upn_tool ──────────────────────────────────────────────
    templates.append((
        [
            f"Search for user {upn}",
            f"Find the user whose email is {upn}",
            f"Look up {upn} in the directory",
        ],
        _plan([_step("s1", "search_user_by_upn_tool", {"user_principal_name": upn})]),
    ))

    # ── create_user_tool ─────────────────────────────────────────────────────
    templates.append((
        [
            f"Create a new user {name} with email {upn}",
            f"Onboard new employee {name}",
            f"Add user {name} ({upn}) to the directory",
        ],
        _plan([_step("s1", "create_user_tool", {
            "user_data": {
                "accountEnabled": True,
                "displayName": name,
                "mailNickname": upn.split("@")[0],
                "userPrincipalName": upn,
                "passwordProfile": {"password": pwd, "forceChangePasswordNextSignIn": True},
            },
        }, desc="Create user account")]),
    ))

    # ── update_user_tool ─────────────────────────────────────────────────────
    templates.append((
        [
            f"Update job title of {upn} to Senior Engineer",
            f"Change the department for user {uid} to Security",
            f"Set office location for {name} to Building 5",
        ],
        _plan([_step("s1", "update_user_tool", {
            "user_id": upn,
            "update_data": {"jobTitle": "Senior Engineer"},
        })]),
    ))

    # ── delete_user_tool ─────────────────────────────────────────────────────
    templates.append((
        [
            f"Delete user {upn}",
            f"Remove user account {uid} from Azure AD",
            f"Offboard user {name} - delete their account",
        ],
        _plan([_step("s1", "delete_user_tool", {"user_id": upn})]),
    ))

    # ── set_user_account_enabled_tool ────────────────────────────────────────
    templates.append((
        [
            f"Disable the account for {upn}",
            f"Block sign-in for user {uid}",
            f"Suspend {name}'s account",
        ],
        _plan([_step("s1", "set_user_account_enabled_tool", {
            "user_id": upn, "account_enabled": False,
        })]),
    ))
    templates.append((
        [
            f"Re-enable account for {upn}",
            f"Unblock user {uid}",
            f"Restore sign-in for {name}",
        ],
        _plan([_step("s1", "set_user_account_enabled_tool", {
            "user_id": upn, "account_enabled": True,
        })]),
    ))

    # ── reset_user_password_tool ─────────────────────────────────────────────
    templates.append((
        [
            f"Reset password for {upn}",
            f"Admin reset password for user {uid} to {pwd}",
            f"Force password reset for {name}",
        ],
        _plan([_step("s1", "reset_user_password_tool", {
            "user_id": upn, "new_password": pwd, "force_change_next_sign_in": True,
        })]),
    ))

    # ── change_user_password_tool ────────────────────────────────────────────
    templates.append((
        [
            f"Change password for {upn} from old to new",
            f"User {upn} wants to change their password",
        ],
        _plan([_step("s1", "change_user_password_tool", {
            "user_id": upn, "current_password": pwd, "new_password": new_pwd,
        })]),
    ))

    # ── validate_user_password_tool ──────────────────────────────────────────
    templates.append((
        [
            f"Check if password '{pwd}' meets policy for user {upn}",
            f"Validate the password strength for {upn}",
        ],
        _plan([_step("s1", "validate_user_password_tool", {
            "user_id": upn, "password": pwd,
        })]),
    ))

    # ── revoke_user_signin_sessions_tool ─────────────────────────────────────
    templates.append((
        [
            f"Revoke all sessions for {upn}",
            f"Force {name} to sign in again",
            f"Sign out user {uid} from all devices",
        ],
        _plan([_step("s1", "revoke_user_signin_sessions_tool", {"user_id": upn})]),
    ))

    # ── invalidate_user_refresh_tokens_tool ──────────────────────────────────
    templates.append((
        [
            f"Invalidate all refresh tokens for {upn}",
            f"Revoke app access tokens for user {uid}",
        ],
        _plan([_step("s1", "invalidate_user_refresh_tokens_tool", {"user_id": upn})]),
    ))

    # ── export_user_personal_data_tool ───────────────────────────────────────
    templates.append((
        [
            f"Export personal data for {upn} to blob storage",
            f"GDPR data export for user {uid}",
        ],
        _plan([_step("s1", "export_user_personal_data_tool", {
            "user_id": upn, "storage_location": storage,
        })]),
    ))

    # ── retry_user_service_provisioning_tool ─────────────────────────────────
    templates.append((
        [
            f"Retry provisioning for {upn}",
            f"Reprovisioning failed services for user {uid}",
        ],
        _plan([_step("s1", "retry_user_service_provisioning_tool", {"user_id": upn})]),
    ))

    # ── convert_external_user_to_internal_tool ───────────────────────────────
    templates.append((
        [
            f"Convert guest user {upn} to internal member",
            f"Change {name} from external guest to internal user",
        ],
        _plan([_step("s1", "convert_external_user_to_internal_tool", {"user_id": upn})]),
    ))

    # ── get_user_delta_tool ───────────────────────────────────────────────────
    templates.append((
        [
            "Get incremental user changes since the last sync",
            "Fetch delta users",
            "What users changed since the last delta query?",
        ],
        _plan([_step("s1", "get_user_delta_tool", {})]),
    ))

    # ── list_user_groups_tool ─────────────────────────────────────────────────
    templates.append((
        [
            f"What groups is {upn} a member of?",
            f"List all groups for user {uid}",
            f"Show group memberships for {name}",
        ],
        _plan([_step("s1", "list_user_groups_tool", {"user_id": upn})]),
    ))

    # ── list_user_registered_devices_tool ────────────────────────────────────
    templates.append((
        [
            f"List devices registered by {upn}",
            f"Show registered devices for user {uid}",
        ],
        _plan([_step("s1", "list_user_registered_devices_tool", {"user_id": upn})]),
    ))

    # ── list_user_directory_roles_tool ───────────────────────────────────────
    templates.append((
        [
            f"What directory roles does {upn} have?",
            f"List admin roles for user {uid}",
        ],
        _plan([_step("s1", "list_user_directory_roles_tool", {"user_id": upn})]),
    ))

    # ── remove_user_from_directory_role_tool ─────────────────────────────────
    templates.append((
        [
            f"Remove {upn} from the Global Administrator role",
            f"Revoke directory role {rng.choice(ROLE_IDS)} from user {uid}",
        ],
        _plan([_step("s1", "remove_user_from_directory_role_tool", {
            "role_id": rng.choice(ROLE_IDS), "directory_object_id": uid,
        })]),
    ))

    # ── add_user_to_group_direct_tool ────────────────────────────────────────
    templates.append((
        [
            f"Add {upn} to group {gid}",
            f"Make {name} a member of group {gid}",
        ],
        _plan([_step("s1", "add_user_to_group_direct_tool", {
            "group_id": gid, "user_id": uid,
        })]),
    ))

    # ── remove_user_from_group_direct_tool ───────────────────────────────────
    templates.append((
        [
            f"Remove {upn} from group {gid}",
            f"Remove {name} from security group {gid}",
        ],
        _plan([_step("s1", "remove_user_from_group_direct_tool", {
            "group_id": gid, "user_id": uid,
        })]),
    ))

    # ── disable_directory_device_tool ────────────────────────────────────────
    templates.append((
        [
            f"Disable device {did} in the directory",
            f"Block directory device {did}",
        ],
        _plan([_step("s1", "disable_directory_device_tool", {
            "device_id": did, "account_enabled": False,
        })]),
    ))

    # ── Group operations ─────────────────────────────────────────────────────
    templates.append((
        [
            "List all groups in the organization",
            "Show all security groups",
            "Get a list of Azure AD groups",
        ],
        _plan([_step("s1", "list_groups_tool", {})]),
    ))

    templates.append((
        [
            f"Get group details for {gid}",
            f"Show info about group {gid}",
        ],
        _plan([_step("s1", "get_group_tool", {"group_id": gid})]),
    ))

    templates.append((
        [
            "Create a new security group called IT-Security-Team",
            "Create group DevOps-Leads as a mail-enabled security group",
        ],
        _plan([_step("s1", "create_group_tool", {
            "group_data": {
                "displayName": "IT-Security-Team",
                "mailEnabled": False,
                "securityEnabled": True,
                "mailNickname": "it-security-team",
            },
        })]),
    ))

    templates.append((
        [
            f"Update description of group {gid} to 'Security Team'",
            f"Rename group {gid} to IT-Ops",
        ],
        _plan([_step("s1", "update_group_tool", {
            "group_id": gid,
            "update_data": {"description": "Security Team"},
        })]),
    ))

    templates.append((
        [
            f"Delete group {gid}",
            f"Remove security group {gid} from the directory",
        ],
        _plan([_step("s1", "delete_group_tool", {"group_id": gid})]),
    ))

    templates.append((
        [
            f"Add user {uid} as a member of group {gid}",
            f"Include {uid} in group {gid}",
        ],
        _plan([_step("s1", "add_group_member_tool", {"group_id": gid, "member_id": uid})]),
    ))

    templates.append((
        [
            f"Remove user {uid} from group {gid}",
            f"Kick {uid} out of group {gid}",
        ],
        _plan([_step("s1", "remove_group_member_tool", {"group_id": gid, "member_id": uid})]),
    ))

    templates.append((
        [
            f"Add user {uid} as owner of group {gid}",
            f"Make {uid} an owner of {gid}",
        ],
        _plan([_step("s1", "add_group_owner_tool", {"group_id": gid, "owner_id": uid})]),
    ))

    templates.append((
        [
            f"Remove owner {uid} from group {gid}",
            f"Strip owner rights of {uid} from group {gid}",
        ],
        _plan([_step("s1", "remove_group_owner_tool", {"group_id": gid, "owner_id": uid})]),
    ))

    templates.append((
        [
            f"List members of group {gid}",
            f"Who is in group {gid}?",
        ],
        _plan([_step("s1", "list_group_members_tool", {"group_id": gid})]),
    ))

    templates.append((
        [
            f"List owners of group {gid}",
            f"Who owns group {gid}?",
        ],
        _plan([_step("s1", "list_group_owners_tool", {"group_id": gid})]),
    ))

    # ── Application operations ───────────────────────────────────────────────
    templates.append((
        [
            "List all application registrations",
            "Show all Azure AD apps",
            "Get list of registered applications",
        ],
        _plan([_step("s1", "list_applications_tool", {})]),
    ))

    templates.append((
        [
            f"Get details of application {app_id}",
            f"Show app registration {app_id}",
        ],
        _plan([_step("s1", "get_application_tool", {"application_id": app_id})]),
    ))

    templates.append((
        [
            "Create a new application called InventoryAPI",
            "Register a new app named DataConnector",
        ],
        _plan([_step("s1", "create_application_tool", {
            "application_data": {"displayName": "InventoryAPI"},
        })]),
    ))

    templates.append((
        [
            f"Update app {app_id} display name to NewAppName",
            f"Change web redirect URI for application {app_id}",
        ],
        _plan([_step("s1", "update_application_tool", {
            "application_id": app_id,
            "update_data": {"displayName": "NewAppName"},
        })]),
    ))

    templates.append((
        [
            f"Delete application {app_id}",
            f"Remove app registration {app_id}",
        ],
        _plan([_step("s1", "delete_application_tool", {"application_id": app_id})]),
    ))

    # ── Device operations ────────────────────────────────────────────────────
    templates.append((
        [
            "List all devices in the directory",
            "Show all registered devices",
        ],
        _plan([_step("s1", "list_devices_tool", {})]),
    ))

    templates.append((
        [
            f"Get device {did}",
            f"Show device info for {did}",
        ],
        _plan([_step("s1", "get_device_tool", {"device_id": did})]),
    ))

    templates.append((
        [
            f"Delete device {did}",
            f"Remove device {did} from the directory",
        ],
        _plan([_step("s1", "delete_device_tool", {"device_id": did})]),
    ))

    templates.append((
        [
            f"List managed devices for user {upn}",
            f"What Intune devices does {name} have?",
        ],
        _plan([_step("s1", "list_managed_devices_for_user_tool", {"user_id": uid})]),
    ))

    templates.append((
        [
            f"Get managed device details for {did}",
            f"Show Intune managed device {did}",
        ],
        _plan([_step("s1", "get_managed_device_tool", {"managed_device_id": did})]),
    ))

    templates.append((
        [
            f"Remotely lock managed device {did}",
            f"Lock the Intune device {did}",
        ],
        _plan([_step("s1", "remote_lock_managed_device_tool", {"managed_device_id": did})]),
    ))

    templates.append((
        [
            f"Wipe managed device {did}",
            f"Factory reset Intune device {did}",
        ],
        _plan([_step("s1", "wipe_managed_device_tool", {"managed_device_id": did})]),
    ))

    templates.append((
        [
            f"Retire managed device {did}",
            f"Remove corporate data from device {did}",
        ],
        _plan([_step("s1", "retire_managed_device_tool", {"managed_device_id": did})]),
    ))

    templates.append((
        [
            f"Sync managed device {did}",
            f"Force policy sync on device {did}",
        ],
        _plan([_step("s1", "sync_managed_device_tool", {"managed_device_id": did})]),
    ))

    templates.append((
        [
            f"Rename managed device {did} to CORP-WS-001",
            f"Set device name for {did}",
        ],
        _plan([_step("s1", "rename_managed_device_tool", {
            "managed_device_id": did, "device_name": "CORP-WS-001",
        })]),
    ))

    templates.append((
        [
            f"Disable lost mode for device {did}",
            f"Turn off lost mode on {did}",
        ],
        _plan([_step("s1", "disable_lost_mode_tool", {"managed_device_id": did})]),
    ))

    templates.append((
        [
            "List all device compliance policies",
            "Show Intune compliance policies",
        ],
        _plan([_step("s1", "list_device_compliance_policies_tool", {})]),
    ))

    templates.append((
        [
            "Get device compliance state summary",
            "How many devices are compliant?",
        ],
        _plan([_step("s1", "get_device_compliance_state_summary_tool", {})]),
    ))

    templates.append((
        [
            "List all device configuration profiles",
            "Show Intune device configurations",
        ],
        _plan([_step("s1", "list_device_configurations_tool", {})]),
    ))

    # ── Security: alerts ─────────────────────────────────────────────────────
    templates.append((
        [
            "List all security alerts",
            "Show recent security alerts",
            f"Get {sev_filter} alerts",
        ],
        _plan([_step("s1", "list_security_alerts_tool", {
            "filter_expression": sev_filter, "top": 50,
        })]),
    ))

    templates.append((
        [
            f"Get security alert {aid}",
            f"Show details of alert {aid}",
        ],
        _plan([_step("s1", "get_security_alert_tool", {"alert_id": aid})]),
    ))

    templates.append((
        [
            f"Resolve security alert {aid}",
            f"Mark alert {aid} as resolved",
            f"Assign alert {aid} to soc@corp.com",
        ],
        _plan([_step("s1", "update_alert_tool", {
            "alert_id": aid,
            "update_data": {"status": "resolved", "assignedTo": "soc@corp.com"},
        })]),
    ))

    # ── Security: incidents ───────────────────────────────────────────────────
    templates.append((
        [
            "List security incidents",
            f"Show incidents with {status_filter}",
            "Get high severity incidents",
        ],
        _plan([_step("s1", "list_security_incidents_tool", {
            "filter_expression": f"severity eq 'high'", "top": 50,
        })]),
    ))

    templates.append((
        [
            f"Get incident {iid}",
            f"Show details of security incident {iid}",
        ],
        _plan([_step("s1", "get_security_incident_tool", {"incident_id": iid})]),
    ))

    templates.append((
        [
            f"Resolve incident {iid}",
            f"Close incident {iid} as a true positive",
            f"Assign incident {iid} to analyst@corp.com",
        ],
        _plan([_step("s1", "update_incident_tool", {
            "incident_id": iid,
            "update_data": {
                "status": "resolved",
                "classification": "truePositive",
                "assignedTo": "analyst@corp.com",
            },
        })]),
    ))

    # ── Security: secure scores ──────────────────────────────────────────────
    templates.append((
        [
            "List secure scores",
            "What is our current secure score?",
            "Show security score history",
        ],
        _plan([_step("s1", "list_secure_scores_tool", {"top": 10})]),
    ))

    templates.append((
        [
            f"Get secure score {rng.choice(SCORE_IDS)}",
            "Retrieve the latest secure score",
        ],
        _plan([_step("s1", "get_secure_score_tool", {"secure_score_id": rng.choice(SCORE_IDS)})]),
    ))

    templates.append((
        [
            "List secure score control profiles",
            "Show all security control recommendations",
        ],
        _plan([_step("s1", "list_secure_score_control_profiles_tool", {})]),
    ))

    profile_id = rng.choice(PROFILE_IDS)
    templates.append((
        [
            f"Get secure score control profile {profile_id}",
            f"Show control profile details for {profile_id}",
        ],
        _plan([_step("s1", "get_secure_score_control_profile_tool", {"profile_id": profile_id})]),
    ))

    templates.append((
        [
            f"Update secure score control profile {profile_id} status to thirdParty",
            f"Mark control {profile_id} as ignored",
        ],
        _plan([_step("s1", "update_secure_score_control_profile_tool", {
            "profile_id": profile_id,
            "update_data": {"controlStateUpdates": [{"assignedTo": "", "comment": "", "state": "thirdParty"}]},
        })]),
    ))

    # ── Identity health ───────────────────────────────────────────────────────
    issue_id = rng.choice(ISSUE_IDS)
    templates.append((
        [
            "List identity health issues",
            "Show Defender for Identity health issues",
        ],
        _plan([_step("s1", "list_identities_health_issues_tool", {})]),
    ))

    templates.append((
        [
            f"Get identity health issue {issue_id}",
            f"Show details of health issue {issue_id}",
        ],
        _plan([_step("s1", "get_identities_health_issue_tool", {"health_issue_id": issue_id})]),
    ))

    templates.append((
        [
            f"Resolve identity health issue {issue_id}",
            f"Mark health issue {issue_id} as resolved",
        ],
        _plan([_step("s1", "update_identities_health_issue_tool", {
            "health_issue_id": issue_id,
            "update_data": {"status": "resolved"},
        })]),
    ))

    # ── Sensors ───────────────────────────────────────────────────────────────
    sensor_id = rng.choice(SENSOR_IDS)
    templates.append((
        [
            "List all Defender for Identity sensors",
            "Show identity sensors",
        ],
        _plan([_step("s1", "list_identities_sensors_tool", {})]),
    ))

    templates.append((
        [
            f"Get sensor {sensor_id}",
            f"Show sensor details {sensor_id}",
        ],
        _plan([_step("s1", "get_identities_sensor_tool", {"sensor_id": sensor_id})]),
    ))

    templates.append((
        [
            f"Update sensor {sensor_id} display name to Primary-DC-Sensor",
            f"Rename sensor {sensor_id}",
        ],
        _plan([_step("s1", "update_identities_sensor_tool", {
            "sensor_id": sensor_id,
            "update_data": {"displayName": "Primary-DC-Sensor"},
        })]),
    ))

    templates.append((
        [
            f"Delete sensor {sensor_id}",
            f"Remove identity sensor {sensor_id}",
        ],
        _plan([_step("s1", "delete_identities_sensor_tool", {"sensor_id": sensor_id})]),
    ))

    # ── Attack simulation ─────────────────────────────────────────────────────
    sim_id = rng.choice(SIM_IDS)
    templates.append((
        [
            "List attack simulations",
            "Show phishing simulation campaigns",
        ],
        _plan([_step("s1", "list_attack_simulations_tool", {})]),
    ))

    templates.append((
        [
            f"Get attack simulation {sim_id}",
            f"Show simulation campaign {sim_id}",
        ],
        _plan([_step("s1", "get_attack_simulation_tool", {"simulation_id": sim_id})]),
    ))

    templates.append((
        [
            "Create a new phishing simulation campaign",
            "Launch an attack simulation for phishing awareness",
        ],
        _plan([_step("s1", "create_attack_simulation_tool", {
            "simulation_data": {
                "displayName": "Q4 Phishing Test",
                "description": "Quarterly phishing awareness simulation",
                "attackType": "phishing",
                "status": "draft",
            },
        })]),
    ))

    templates.append((
        [
            f"Update simulation {sim_id} status to completed",
            f"Mark simulation {sim_id} as cancelled",
        ],
        _plan([_step("s1", "update_attack_simulation_tool", {
            "simulation_id": sim_id,
            "update_data": {"status": "completed"},
        })]),
    ))

    templates.append((
        [
            f"Delete simulation {sim_id}",
            f"Remove attack simulation campaign {sim_id}",
        ],
        _plan([_step("s1", "delete_attack_simulation_tool", {"simulation_id": sim_id})]),
    ))

    templates.append((
        [
            f"Get payload for simulation {sim_id}",
            f"Show the email payload used in simulation {sim_id}",
        ],
        _plan([_step("s1", "get_simulation_payload_tool", {"simulation_id": sim_id})]),
    ))

    templates.append((
        [
            f"Get login page for simulation {sim_id}",
            f"Show login page of simulation {sim_id}",
        ],
        _plan([_step("s1", "get_simulation_login_page_tool", {"simulation_id": sim_id})]),
    ))

    templates.append((
        [
            f"Get landing page for simulation {sim_id}",
            f"Show landing page of attack simulation {sim_id}",
        ],
        _plan([_step("s1", "get_simulation_landing_page_tool", {"simulation_id": sim_id})]),
    ))

    # ── eDiscovery ────────────────────────────────────────────────────────────
    case_id = rng.choice(CASE_IDS)
    templates.append((
        [
            "List all eDiscovery cases",
            "Show compliance eDiscovery cases",
        ],
        _plan([_step("s1", "list_ediscovery_cases_tool", {})]),
    ))

    templates.append((
        [
            f"Get eDiscovery case {case_id}",
            f"Show case details {case_id}",
        ],
        _plan([_step("s1", "get_ediscovery_case_tool", {"case_id": case_id})]),
    ))

    templates.append((
        [
            "Create a new eDiscovery case for HR investigation",
            "Open a compliance case for legal hold",
        ],
        _plan([_step("s1", "create_ediscovery_case_tool", {
            "case_data": {
                "displayName": "HR Investigation Q4",
                "description": "Legal hold for HR investigation",
            },
        })]),
    ))

    templates.append((
        [
            f"Update eDiscovery case {case_id} to closed",
            f"Close case {case_id}",
        ],
        _plan([_step("s1", "update_ediscovery_case_tool", {
            "case_id": case_id,
            "update_data": {"status": "closed"},
        })]),
    ))

    templates.append((
        [
            f"Delete eDiscovery case {case_id}",
            f"Remove compliance case {case_id}",
        ],
        _plan([_step("s1", "delete_ediscovery_case_tool", {"case_id": case_id})]),
    ))

    templates.append((
        [
            f"List operations for eDiscovery case {case_id}",
            f"What operations are running in case {case_id}?",
        ],
        _plan([_step("s1", "get_ediscovery_case_operations_tool", {"case_id": case_id})]),
    ))

    # ── Threat intelligence ───────────────────────────────────────────────────
    ind_id = rng.choice(INDICATOR_IDS)
    templates.append((
        [
            "List threat intelligence indicators",
            "Show TI indicators in the tenant",
        ],
        _plan([_step("s1", "list_threat_intelligence_indicators_tool", {})]),
    ))

    templates.append((
        [
            f"Get threat indicator {ind_id}",
            f"Show TI indicator {ind_id}",
        ],
        _plan([_step("s1", "get_threat_intelligence_indicator_tool", {"indicator_id": ind_id})]),
    ))

    templates.append((
        [
            "Create a threat indicator for IP 198.51.100.1 with block action",
            "Add a new TI indicator for a malicious IP",
        ],
        _plan([_step("s1", "create_threat_intelligence_indicator_tool", {
            "indicator_data": {
                "action": "block",
                "activityGroupNames": [],
                "confidence": 85,
                "description": "Known C2 server",
                "expirationDateTime": "2025-12-31T00:00:00Z",
                "indicatorType": "ipAddress",
                "networkIPv4": "198.51.100.1",
                "tlpLevel": "white",
            },
        })]),
    ))

    templates.append((
        [
            f"Update threat indicator {ind_id} confidence to 90",
            f"Change action of indicator {ind_id} to alert",
        ],
        _plan([_step("s1", "update_threat_intelligence_indicator_tool", {
            "indicator_id": ind_id,
            "update_data": {"confidence": 90, "action": "alert"},
        })]),
    ))

    templates.append((
        [
            f"Delete threat intelligence indicator {ind_id}",
            f"Remove TI indicator {ind_id}",
        ],
        _plan([_step("s1", "delete_threat_intelligence_indicator_tool", {"indicator_id": ind_id})]),
    ))

    # ── Threat submissions ────────────────────────────────────────────────────
    sub_id = rng.choice(SUBMISSION_IDS)
    templates.append((
        [
            "List all threat submissions",
            "Show reported phishing emails",
        ],
        _plan([_step("s1", "list_threat_submissions_tool", {})]),
    ))

    templates.append((
        [
            f"Get threat submission {sub_id}",
            f"Show submission {sub_id} details",
        ],
        _plan([_step("s1", "get_threat_submission_tool", {"submission_id": sub_id})]),
    ))

    templates.append((
        [
            "Submit a phishing email for analysis",
            "Report a suspicious URL to Microsoft",
        ],
        _plan([_step("s1", "create_threat_submission_tool", {
            "submission_data": {
                "category": "phishing",
                "recipientEmailAddress": upn,
                "subject": "Suspicious Email Subject",
            },
        })]),
    ))

    # ── Visibility / audit ────────────────────────────────────────────────────
    templates.append((
        [
            f"Show sign-in logs for {upn}",
            "List recent sign-in events",
            f"Get sign-in history for {name}",
        ],
        _plan([_step("s1", "list_sign_in_logs_tool", {
            "user_principal_name": upn, "top": 50,
        })]),
    ))

    templates.append((
        [
            "List directory audit logs",
            "Show audit events in Azure AD",
        ],
        _plan([_step("s1", "list_directory_audits_tool", {"top": 100})]),
    ))

    templates.append((
        [
            "List risky users",
            "Show users flagged by identity protection",
            "Who are the high-risk users?",
        ],
        _plan([_step("s1", "list_risky_users_tool", {})]),
    ))

    templates.append((
        [
            "List risk detections",
            "Show identity protection risk events",
        ],
        _plan([_step("s1", "list_risk_detections_tool", {})]),
    ))

    # ── App / OAuth ───────────────────────────────────────────────────────────
    templates.append((
        [
            "List recently registered applications",
            "Show new app registrations",
        ],
        _plan([_step("s1", "list_recent_applications_tool", {"top": 25})]),
    ))

    templates.append((
        [
            f"Disable service principal {uid}",
            f"Block app access for service principal {uid}",
        ],
        _plan([_step("s1", "disable_service_principal_tool", {
            "service_principal_id": uid, "account_enabled": False,
        })]),
    ))

    templates.append((
        [
            f"List service principals for appId {app_id}",
            f"Find service principals matching app {app_id}",
        ],
        _plan([_step("s1", "list_service_principals_by_appid_tool", {"app_id": app_id})]),
    ))

    templates.append((
        [
            f"Remove app password key {rng.choice(KEY_IDS)} from application {app_id}",
            f"Delete client secret from app {app_id}",
        ],
        _plan([_step("s1", "remove_application_password_tool", {
            "application_id": app_id, "key_id": rng.choice(KEY_IDS),
        })]),
    ))

    templates.append((
        [
            "List all OAuth permission grants",
            "Show delegated permission grants",
        ],
        _plan([_step("s1", "list_oauth_permission_grants_tool", {})]),
    ))

    templates.append((
        [
            f"Delete OAuth permission grant {rng.choice(GRANT_IDS)}",
            f"Revoke delegated permission grant {rng.choice(GRANT_IDS)}",
        ],
        _plan([_step("s1", "delete_oauth_permission_grant_tool", {
            "grant_id": rng.choice(GRANT_IDS),
        })]),
    ))

    # ── Mailbox ───────────────────────────────────────────────────────────────
    rule_id = rng.choice(RULE_IDS)
    templates.append((
        [
            f"List inbox rules for {upn}",
            f"Show mailbox rules configured by {name}",
        ],
        _plan([_step("s1", "list_inbox_rules_tool", {"user_id": uid})]),
    ))

    templates.append((
        [
            f"Delete inbox rule {rule_id} for user {upn}",
            f"Remove mailbox rule {rule_id} from {name}",
        ],
        _plan([_step("s1", "delete_inbox_rule_tool", {"user_id": uid, "rule_id": rule_id})]),
    ))

    templates.append((
        [
            f"Search {upn}'s mailbox for 'invoice'",
            f"Find emails with subject 'payroll' in {name}'s mailbox",
        ],
        _plan([_step("s1", "search_user_messages_tool", {
            "user_id": uid,
            "search_query": "\"invoice\"",
            "top": 25,
        })]),
    ))

    # ── Generic ───────────────────────────────────────────────────────────────
    templates.append((
        [
            "Discover operations available for the users resource",
            "What operations are supported for groups?",
        ],
        _plan([_step("s1", "list_resource_operations_tool", {"resource_type": "users"})]),
    ))

    templates.append((
        [
            "What fields are available on the security/alerts_v2 resource?",
            "Inspect the schema for users",
        ],
        _plan([_step("s1", "get_graph_resource_schema_tool", {"resource_name": "users"})]),
    ))

    templates.append((
        [
            "Use generic Graph operation tool to list 10 users",
            "Run a raw operation to fetch the top 10 users",
        ],
        _plan([_step("s1", "graph_operation_tool", {
            "resource_type": "users",
            "operation": "list",
            "query_params": {"$top": 10},
        })], confidence=0.9),
    ))

    return templates


# ---------------------------------------------------------------------------
# Multi-step workflow templates
# ---------------------------------------------------------------------------

def build_multistep_templates(rng: random.Random) -> list[tuple[list[str], dict]]:
    uid = _rng_uid(rng)
    upn = _rng_upn(rng)
    name = _rng_name(rng)
    gid = _rng_gid(rng)
    did = _rng_did(rng)
    aid = _rng_aid(rng)
    iid = _rng_iid(rng)
    pwd = _rng_pwd(rng)
    new_pwd = _rng_pwd(rng)
    app_id = rng.choice(APP_GUIDS)
    sensor_id = rng.choice(SENSOR_IDS)
    issue_id = rng.choice(ISSUE_IDS)
    profile_id = rng.choice(PROFILE_IDS)
    sim_id = rng.choice(SIM_IDS)
    case_id = rng.choice(CASE_IDS)
    ind_id = rng.choice(INDICATOR_IDS)
    rule_id = rng.choice(RULE_IDS)
    role_id = rng.choice(ROLE_IDS)

    templates: list[tuple[list[str], dict]] = []

    # ── 1. Disable user by UPN (lookup → disable) ────────────────────────────
    templates.append((
        [
            f"Disable account for {upn}",
            f"Block sign-in for user {name} ({upn})",
            f"Suspend {upn} - set accountEnabled to false",
        ],
        _plan([
            _step("s1", "search_user_by_upn_tool", {"user_principal_name": upn},
                  desc="Resolve UPN to object ID"),
            _step("s2", "set_user_account_enabled_tool",
                  {"user_id": "$s1.id", "account_enabled": False}, ["s1"],
                  desc="Disable the account"),
        ], confidence=0.97),
    ))

    # ── 2. Disable + revoke sessions ─────────────────────────────────────────
    templates.append((
        [
            f"Disable {upn} and revoke all their sessions",
            f"Block {name} and sign them out from all devices",
            f"Suspend {upn}: disable account and revoke sessions",
        ],
        _plan([
            _step("s1", "search_user_by_upn_tool", {"user_principal_name": upn},
                  desc="Find user"),
            _step("s2", "set_user_account_enabled_tool",
                  {"user_id": "$s1.id", "account_enabled": False}, ["s1"],
                  desc="Disable account"),
            _step("s3", "revoke_user_signin_sessions_tool",
                  {"user_id": "$s1.id"}, ["s1"],
                  desc="Revoke sessions"),
        ], confidence=0.96),
    ))

    # ── 3. Full offboarding ───────────────────────────────────────────────────
    templates.append((
        [
            f"Offboard user {upn}: disable account, revoke sessions, and invalidate tokens",
            f"Terminate {name}'s access completely",
            f"Full security lockout for {upn}",
        ],
        _plan([
            _step("s1", "search_user_by_upn_tool", {"user_principal_name": upn},
                  desc="Resolve user"),
            _step("s2", "set_user_account_enabled_tool",
                  {"user_id": "$s1.id", "account_enabled": False}, ["s1"],
                  desc="Disable account"),
            _step("s3", "revoke_user_signin_sessions_tool",
                  {"user_id": "$s1.id"}, ["s1"],
                  desc="Revoke sessions"),
            _step("s4", "invalidate_user_refresh_tokens_tool",
                  {"user_id": "$s1.id"}, ["s1"],
                  desc="Invalidate tokens"),
        ], confidence=0.95),
    ))

    # ── 4. Add user to group by UPN ───────────────────────────────────────────
    templates.append((
        [
            f"Add {upn} to group {gid}",
            f"Include {name} ({upn}) in security group {gid}",
            f"Make {upn} a member of {gid}",
        ],
        _plan([
            _step("s1", "search_user_by_upn_tool", {"user_principal_name": upn},
                  desc="Resolve UPN to ID"),
            _step("s2", "add_user_to_group_direct_tool",
                  {"group_id": gid, "user_id": "$s1.id"}, ["s1"],
                  desc="Add to group"),
        ], confidence=0.96),
    ))

    # ── 5. Remove user from group by UPN ──────────────────────────────────────
    templates.append((
        [
            f"Remove {upn} from group {gid}",
            f"Kick {name} out of security group {gid}",
        ],
        _plan([
            _step("s1", "search_user_by_upn_tool", {"user_principal_name": upn}),
            _step("s2", "remove_user_from_group_direct_tool",
                  {"group_id": gid, "user_id": "$s1.id"}, ["s1"]),
        ], confidence=0.95),
    ))

    # ── 6. Reset password + revoke sessions ───────────────────────────────────
    templates.append((
        [
            f"Reset password for {upn} and sign them out",
            f"Change {name}'s password to {pwd} and revoke all sessions",
        ],
        _plan([
            _step("s1", "search_user_by_upn_tool", {"user_principal_name": upn}),
            _step("s2", "reset_user_password_tool",
                  {"user_id": "$s1.id", "new_password": pwd, "force_change_next_sign_in": True},
                  ["s1"], desc="Reset password"),
            _step("s3", "revoke_user_signin_sessions_tool",
                  {"user_id": "$s1.id"}, ["s1"], desc="Revoke sessions"),
        ], confidence=0.95),
    ))

    # ── 7. Find user then list their groups ───────────────────────────────────
    templates.append((
        [
            f"What groups does {upn} belong to?",
            f"Show all group memberships for {name} ({upn})",
        ],
        _plan([
            _step("s1", "search_user_by_upn_tool", {"user_principal_name": upn}),
            _step("s2", "list_user_groups_tool", {"user_id": "$s1.id"}, ["s1"]),
        ], confidence=0.96),
    ))

    # ── 8. Find user then list their devices ──────────────────────────────────
    templates.append((
        [
            f"What devices does {upn} have registered in Intune?",
            f"List managed devices for user {name}",
        ],
        _plan([
            _step("s1", "search_user_by_upn_tool", {"user_principal_name": upn}),
            _step("s2", "list_managed_devices_for_user_tool", {"user_id": "$s1.id"}, ["s1"]),
        ], confidence=0.95),
    ))

    # ── 9. Alert → assign to analyst ──────────────────────────────────────────
    templates.append((
        [
            f"Assign alert {aid} to analyst@corp.com and mark it in progress",
            f"Triage alert {aid}: assign and set status to inProgress",
        ],
        _plan([
            _step("s1", "get_security_alert_tool", {"alert_id": aid},
                  desc="Fetch alert details"),
            _step("s2", "update_alert_tool",
                  {"alert_id": aid,
                   "update_data": {"status": "inProgress", "assignedTo": "analyst@corp.com"}},
                  ["s1"], desc="Update alert"),
        ], confidence=0.95),
    ))

    # ── 10. Incident → resolve ────────────────────────────────────────────────
    templates.append((
        [
            f"Resolve incident {iid} as a true positive and assign it",
            f"Close incident {iid}: true positive, assign to soc@corp.com",
        ],
        _plan([
            _step("s1", "get_security_incident_tool", {"incident_id": iid}),
            _step("s2", "update_incident_tool", {
                "incident_id": iid,
                "update_data": {
                    "status": "resolved",
                    "classification": "truePositive",
                    "assignedTo": "soc@corp.com",
                },
            }, ["s1"]),
        ], confidence=0.94),
    ))

    # ── 11. List alerts + incidents in parallel ────────────────────────────────
    templates.append((
        [
            "Get both security alerts and incidents at once",
            "Fetch high-severity alerts and active incidents simultaneously",
        ],
        _plan([
            _step("s1", "list_security_alerts_tool",
                  {"filter_expression": "severity eq 'high'", "top": 50}, [],
                  desc="Fetch high-severity alerts"),
            _step("s2", "list_security_incidents_tool",
                  {"filter_expression": "status eq 'active'", "top": 50}, [],
                  desc="Fetch active incidents"),
        ], confidence=0.93),
    ))

    # ── 12. Service principal → disable OAuth grants ──────────────────────────
    templates.append((
        [
            f"Find service principals for app {app_id} and list their OAuth grants",
            f"Show delegated permissions for app {app_id}",
        ],
        _plan([
            _step("s1", "list_service_principals_by_appid_tool", {"app_id": app_id}),
            _step("s2", "list_oauth_permission_grants_tool",
                  {"service_principal_id": "$s1.id"}, ["s1"]),
        ], confidence=0.92),
    ))

    # ── 13. App secret cleanup ────────────────────────────────────────────────
    templates.append((
        [
            f"Remove all secrets from application {app_id}",
            f"Delete client secret from app {app_id}",
        ],
        _plan([
            _step("s1", "get_application_tool", {"application_id": app_id},
                  desc="Get app to find key ID"),
            _step("s2", "remove_application_password_tool",
                  {"application_id": app_id, "key_id": rng.choice(KEY_IDS)}, ["s1"],
                  desc="Remove the secret"),
        ], confidence=0.91),
    ))

    # ── 14. User mailbox rule audit ───────────────────────────────────────────
    templates.append((
        [
            f"Audit inbox rules for {upn} and remove suspicious rule {rule_id}",
            f"Check and clean inbox rules for {name}",
        ],
        _plan([
            _step("s1", "search_user_by_upn_tool", {"user_principal_name": upn}),
            _step("s2", "list_inbox_rules_tool", {"user_id": "$s1.id"}, ["s1"]),
            _step("s3", "delete_inbox_rule_tool",
                  {"user_id": "$s1.id", "rule_id": rule_id}, ["s1"],
                  desc="Remove the suspicious rule"),
        ], confidence=0.90),
    ))

    # ── 15. Sign-in + risk check ───────────────────────────────────────────────
    templates.append((
        [
            f"Check sign-in logs and risk detections for {upn}",
            f"Investigate {name}'s sign-in activity and risk events",
        ],
        _plan([
            _step("s1", "search_user_by_upn_tool", {"user_principal_name": upn}),
            _step("s2", "list_sign_in_logs_tool",
                  {"user_principal_name": upn, "top": 50}, ["s1"],
                  desc="Get sign-in history"),
            _step("s3", "list_risk_detections_tool", {}, [],
                  desc="Get risk detections"),
        ], confidence=0.92),
    ))

    # ── 16. Remove user from directory role by UPN ────────────────────────────
    templates.append((
        [
            f"Remove {upn} from directory role {role_id}",
            f"Revoke admin role {role_id} from user {name}",
        ],
        _plan([
            _step("s1", "search_user_by_upn_tool", {"user_principal_name": upn}),
            _step("s2", "remove_user_from_directory_role_tool",
                  {"role_id": role_id, "directory_object_id": "$s1.id"}, ["s1"]),
        ], confidence=0.95),
    ))

    # ── 17. Wipe + retire device ──────────────────────────────────────────────
    templates.append((
        [
            f"Wipe device {did} and then delete its record",
            f"Fully remove device {did} from Intune",
        ],
        _plan([
            _step("s1", "wipe_managed_device_tool", {"managed_device_id": did},
                  desc="Factory wipe"),
            _step("s2", "delete_managed_device_record_tool",
                  {"managed_device_id": did}, ["s1"],
                  desc="Delete record"),
        ], confidence=0.93),
    ))

    # ── 18. Attack sim → get payload and landing page ─────────────────────────
    templates.append((
        [
            f"Get the payload and landing page for simulation {sim_id}",
            f"Fetch simulation artifacts (payload + landing page) for {sim_id}",
        ],
        _plan([
            _step("s1", "get_simulation_payload_tool", {"simulation_id": sim_id}, [],
                  desc="Get payload"),
            _step("s2", "get_simulation_landing_page_tool", {"simulation_id": sim_id}, [],
                  desc="Get landing page"),
        ], confidence=0.94),
    ))

    # ── 19. eDiscovery case + operations ──────────────────────────────────────
    templates.append((
        [
            f"Get case {case_id} and list its operations",
            f"Show details and running operations for eDiscovery case {case_id}",
        ],
        _plan([
            _step("s1", "get_ediscovery_case_tool", {"case_id": case_id}),
            _step("s2", "get_ediscovery_case_operations_tool",
                  {"case_id": case_id}, ["s1"]),
        ], confidence=0.95),
    ))

    # ── 20. Create TI indicator + list all ────────────────────────────────────
    templates.append((
        [
            "Add a new threat indicator for malicious domain badactor.example.com and list all indicators",
            "Submit a threat indicator for a C2 domain and verify it was added",
        ],
        _plan([
            _step("s1", "create_threat_intelligence_indicator_tool", {
                "indicator_data": {
                    "action": "block",
                    "confidence": 90,
                    "description": "Known C2 domain",
                    "expirationDateTime": "2025-12-31T00:00:00Z",
                    "indicatorType": "domainName",
                    "domainName": "badactor.example.com",
                    "tlpLevel": "white",
                },
            }, [], desc="Create indicator"),
            _step("s2", "list_threat_intelligence_indicators_tool", {}, ["s1"],
                  desc="Verify it was added"),
        ], confidence=0.92),
    ))

    # ── 21. Update identity health issue + get sensor ─────────────────────────
    templates.append((
        [
            f"Resolve health issue {issue_id} and get sensor {sensor_id} info",
            f"Fix identity health issue {issue_id} and check sensor status",
        ],
        _plan([
            _step("s1", "update_identities_health_issue_tool", {
                "health_issue_id": issue_id,
                "update_data": {"status": "resolved"},
            }, [], desc="Resolve health issue"),
            _step("s2", "get_identities_sensor_tool",
                  {"sensor_id": sensor_id}, [],
                  desc="Check sensor status"),
        ], confidence=0.91),
    ))

    # ── 22. Secure score + update control ────────────────────────────────────
    templates.append((
        [
            f"Get latest secure score and mark control {profile_id} as thirdParty",
            "Check secure score and update a control profile",
        ],
        _plan([
            _step("s1", "list_secure_scores_tool", {"top": 1}, [],
                  desc="Get latest score"),
            _step("s2", "update_secure_score_control_profile_tool", {
                "profile_id": profile_id,
                "update_data": {
                    "controlStateUpdates": [{"assignedTo": "", "comment": "", "state": "thirdParty"}],
                },
            }, [], desc="Update control"),
        ], confidence=0.92),
    ))

    # ── 23. Create group + add member ─────────────────────────────────────────
    templates.append((
        [
            f"Create a new security group DevOps-Leads and add {upn} to it",
            f"Set up group DevOps-Leads and include {name}",
        ],
        _plan([
            _step("s1", "search_user_by_upn_tool", {"user_principal_name": upn},
                  desc="Resolve user ID"),
            _step("s2", "create_group_tool", {
                "group_data": {
                    "displayName": "DevOps-Leads",
                    "mailEnabled": False,
                    "securityEnabled": True,
                    "mailNickname": "devops-leads",
                },
            }, [], desc="Create group"),
            _step("s3", "add_group_member_tool",
                  {"group_id": "$s2.id", "member_id": "$s1.id"}, ["s1", "s2"],
                  desc="Add member"),
        ], confidence=0.90),
    ))

    # ── 24. Delete OAuth grant + disable service principal ────────────────────
    templates.append((
        [
            f"Revoke OAuth grant {rng.choice(GRANT_IDS)} and disable service principal {uid}",
            f"Remove permission grant and block service principal {uid}",
        ],
        _plan([
            _step("s1", "delete_oauth_permission_grant_tool",
                  {"grant_id": rng.choice(GRANT_IDS)}, [],
                  desc="Delete OAuth grant"),
            _step("s2", "disable_service_principal_tool",
                  {"service_principal_id": uid, "account_enabled": False}, [],
                  desc="Disable service principal"),
        ], confidence=0.93),
    ))

    # ── 25. Full compromised account response ─────────────────────────────────
    templates.append((
        [
            f"Respond to compromised account {upn}: disable, revoke tokens, reset password, and check sign-ins",
            f"Incident response for {name}: full account lockout and investigation",
        ],
        _plan([
            _step("s1", "search_user_by_upn_tool", {"user_principal_name": upn},
                  desc="Resolve account"),
            _step("s2", "set_user_account_enabled_tool",
                  {"user_id": "$s1.id", "account_enabled": False}, ["s1"],
                  desc="Disable account"),
            _step("s3", "revoke_user_signin_sessions_tool",
                  {"user_id": "$s1.id"}, ["s1"],
                  desc="Revoke sessions"),
            _step("s4", "invalidate_user_refresh_tokens_tool",
                  {"user_id": "$s1.id"}, ["s1"],
                  desc="Invalidate tokens"),
            _step("s5", "reset_user_password_tool",
                  {"user_id": "$s1.id", "new_password": pwd, "force_change_next_sign_in": True},
                  ["s1"], desc="Reset password"),
            _step("s6", "list_sign_in_logs_tool",
                  {"user_principal_name": upn, "top": 50}, ["s1"],
                  desc="Audit sign-ins"),
        ], confidence=0.93),
    ))

    return templates


# ---------------------------------------------------------------------------
# Record builder
# ---------------------------------------------------------------------------

def make_record(
    query: str,
    plan: dict,
    difficulty: str,
    category: str,
    split: str,
    generated_at: str,
) -> dict:
    tools_used = [s["tool"] for s in plan["steps"]]
    is_multi = len(plan["steps"]) > 1
    return {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": query},
            {"role": "assistant", "content": json.dumps(plan, separators=(",", ":"))},
        ],
        "meta": {
            "source": "synthetic_workflow",
            "difficulty": difficulty,
            "category": category,
            "tools": tools_used,
            "is_multi_step": is_multi,
            "step_count": len(plan["steps"]),
            "split": split,
            "generated_at": generated_at,
        },
    }


def categorise(tools_used: list[str]) -> str:
    if not tools_used:
        return "clarification"
    cats = {
        "user_management": {"get_user_tool", "create_user_tool", "update_user_tool",
                            "delete_user_tool", "search_user_by_upn_tool",
                            "set_user_account_enabled_tool", "reset_user_password_tool",
                            "change_user_password_tool", "validate_user_password_tool",
                            "revoke_user_signin_sessions_tool", "invalidate_user_refresh_tokens_tool",
                            "export_user_personal_data_tool", "retry_user_service_provisioning_tool",
                            "convert_external_user_to_internal_tool", "get_user_delta_tool",
                            "list_user_groups_tool", "list_user_registered_devices_tool",
                            "list_user_directory_roles_tool", "remove_user_from_directory_role_tool",
                            "add_user_to_group_direct_tool", "remove_user_from_group_direct_tool",
                            "disable_directory_device_tool"},
        "group_management": {"list_groups_tool", "get_group_tool", "create_group_tool",
                             "update_group_tool", "delete_group_tool", "add_group_member_tool",
                             "remove_group_member_tool", "add_group_owner_tool",
                             "remove_group_owner_tool", "list_group_members_tool",
                             "list_group_owners_tool"},
        "application_management": {"list_applications_tool", "get_application_tool",
                                   "create_application_tool", "update_application_tool",
                                   "delete_application_tool", "list_recent_applications_tool",
                                   "disable_service_principal_tool",
                                   "list_service_principals_by_appid_tool",
                                   "remove_application_password_tool",
                                   "list_oauth_permission_grants_tool",
                                   "delete_oauth_permission_grant_tool"},
        "device_management": {"list_devices_tool", "get_device_tool", "delete_device_tool",
                              "list_managed_devices_for_user_tool", "get_managed_device_tool",
                              "remote_lock_managed_device_tool", "wipe_managed_device_tool",
                              "retire_managed_device_tool", "delete_managed_device_record_tool",
                              "sync_managed_device_tool", "rename_managed_device_tool",
                              "disable_lost_mode_tool", "list_device_compliance_policies_tool",
                              "get_device_compliance_state_summary_tool",
                              "list_device_configurations_tool"},
        "security_operations": {"list_security_alerts_tool", "get_security_alert_tool",
                                "update_alert_tool", "list_security_incidents_tool",
                                "get_security_incident_tool", "update_incident_tool",
                                "list_secure_scores_tool", "get_secure_score_tool",
                                "list_secure_score_control_profiles_tool",
                                "get_secure_score_control_profile_tool",
                                "update_secure_score_control_profile_tool",
                                "list_identities_health_issues_tool",
                                "get_identities_health_issue_tool",
                                "update_identities_health_issue_tool",
                                "list_identities_sensors_tool", "get_identities_sensor_tool",
                                "update_identities_sensor_tool", "delete_identities_sensor_tool",
                                "list_attack_simulations_tool", "get_attack_simulation_tool",
                                "create_attack_simulation_tool", "update_attack_simulation_tool",
                                "delete_attack_simulation_tool", "get_simulation_payload_tool",
                                "get_simulation_login_page_tool", "get_simulation_landing_page_tool",
                                "list_ediscovery_cases_tool", "get_ediscovery_case_tool",
                                "create_ediscovery_case_tool", "update_ediscovery_case_tool",
                                "delete_ediscovery_case_tool", "get_ediscovery_case_operations_tool",
                                "list_threat_intelligence_indicators_tool",
                                "get_threat_intelligence_indicator_tool",
                                "create_threat_intelligence_indicator_tool",
                                "update_threat_intelligence_indicator_tool",
                                "delete_threat_intelligence_indicator_tool",
                                "list_threat_submissions_tool", "get_threat_submission_tool",
                                "create_threat_submission_tool"},
        "audit_visibility": {"list_sign_in_logs_tool", "list_directory_audits_tool",
                             "list_risky_users_tool", "list_risk_detections_tool"},
    }
    tool_set = set(tools_used)
    for cat, cat_tools in cats.items():
        if tool_set & cat_tools:
            return cat
    return "generic"


def _sample_arg_value(arg_name: str, arg_type: str, rng: random.Random) -> Any:
    lname = arg_name.lower()
    if lname in {"user_id", "directory_object_id", "member_id", "owner_id"}:
        return rng.choice(GUIDS)
    if lname in {"group_id"}:
        return rng.choice(GROUP_GUIDS)
    if lname in {"device_id"}:
        return rng.choice(DEVICE_GUIDS)
    if lname in {"managed_device_id"}:
        return rng.choice(DEVICE_GUIDS)
    if lname in {"application_id", "service_principal_id"}:
        return rng.choice(APP_GUIDS)
    if lname in {"alert_id"}:
        return rng.choice(ALERT_IDS)
    if lname in {"incident_id"}:
        return rng.choice(INCIDENT_IDS)
    if lname in {"profile_id"}:
        return rng.choice(PROFILE_IDS)
    if lname in {"health_issue_id"}:
        return rng.choice(ISSUE_IDS)
    if lname in {"sensor_id"}:
        return rng.choice(SENSOR_IDS)
    if lname in {"simulation_id"}:
        return rng.choice(SIM_IDS)
    if lname in {"case_id"}:
        return rng.choice(CASE_IDS)
    if lname in {"indicator_id"}:
        return rng.choice(INDICATOR_IDS)
    if lname in {"submission_id"}:
        return rng.choice(SUBMISSION_IDS)
    if lname in {"rule_id"}:
        return rng.choice(RULE_IDS)
    if lname in {"grant_id"}:
        return rng.choice(GRANT_IDS)
    if lname in {"key_id"}:
        return rng.choice(KEY_IDS)
    if lname in {"secure_score_id"}:
        return rng.choice(SCORE_IDS)
    if lname in {"resource_type"}:
        return "users"
    if lname in {"operation"}:
        return "list"
    if lname in {"resource_name"}:
        return "users"
    if lname in {"user_principal_name", "upn", "mail", "recipientemailaddress"}:
        return rng.choice(UPNS)
    if lname in {"search_query"}:
        return "\"invoice\""
    if lname in {"top"}:
        return 10
    if lname in {"account_enabled"}:
        return False
    if lname in {"new_password", "current_password", "password"}:
        return rng.choice(PASSWORDS)
    if lname in {"storage_location"}:
        return rng.choice(STORAGE_LOCATIONS)

    if arg_type == "bool":
        return True
    if arg_type == "int":
        return 10
    if arg_type == "list[str]":
        return ["id", "displayName"]
    if arg_type == "dict":
        if lname == "update_data":
            return {"status": "active"}
        if lname == "query_params":
            return {"$top": 10}
        if lname == "path_params":
            return {}
        if lname == "user_data":
            upn = rng.choice(UPNS)
            return {
                "accountEnabled": True,
                "displayName": rng.choice(DISPLAY_NAMES),
                "mailNickname": upn.split("@")[0],
                "userPrincipalName": upn,
                "passwordProfile": {
                    "password": rng.choice(PASSWORDS),
                    "forceChangePasswordNextSignIn": True,
                },
            }
        if lname == "group_data":
            return {
                "displayName": "SOC-Analysts",
                "mailEnabled": False,
                "securityEnabled": True,
                "mailNickname": "soc-analysts",
            }
        if lname == "application_data":
            return {"displayName": "AutomationApp"}
        if lname == "submission_data":
            return {
                "category": "phishing",
                "recipientEmailAddress": rng.choice(UPNS),
                "subject": "Suspicious Email Subject",
            }
        if lname == "indicator_data":
            return {
                "action": "block",
                "confidence": 85,
                "indicatorType": "ipAddress",
                "networkIPv4": "198.51.100.1",
                "tlpLevel": "white",
                "expirationDateTime": "2026-12-31T00:00:00Z",
                "description": "Known malicious IP",
            }
        return {"value": "example"}
    return "example"


def _auto_args_for_tool(tool_name: str, rng: random.Random) -> dict[str, Any]:
    args_schema = TOOL_CATALOG[tool_name].get("args", {})
    args: dict[str, Any] = {}
    for arg_name, arg_type in args_schema.items():
        args[arg_name] = _sample_arg_value(arg_name, arg_type, rng)
    return args


def _coverage_record_for_tool(tool_name: str, generated_at: str, rng: random.Random) -> dict[str, Any]:
    if tool_name == "graph_operation_tool":
        query = "Use generic Graph operation tool to list users"
        args = {"resource_type": "users", "operation": "list", "query_params": {"$top": 10}}
    elif tool_name == "get_managed_device_tool":
        did = rng.choice(DEVICE_GUIDS)
        query = f"Get Intune managed device details for {did}"
        args = {"managed_device_id": did}
    elif tool_name == "get_secure_score_control_profile_tool":
        pid = rng.choice(PROFILE_IDS)
        query = f"Get secure score control profile {pid}"
        args = {"profile_id": pid}
    else:
        desc = TOOL_CATALOG[tool_name]["desc"].rstrip(".")
        query = f"{desc}"
        args = _auto_args_for_tool(tool_name, rng)

    plan = _plan([_step("s1", tool_name, args)], confidence=0.88)
    return make_record(
        query=query,
        plan=plan,
        difficulty=_difficulty_for_plan(plan),
        category=categorise([tool_name]),
        split="train",
        generated_at=generated_at,
    )


def _dedupe_records_by_query(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen_queries: set[str] = set()
    for rec in records:
        query = rec["messages"][1]["content"]
        norm_query = _normalize_query(query)
        if norm_query in seen_queries:
            continue
        seen_queries.add(norm_query)
        deduped.append(rec)
    return deduped


# ---------------------------------------------------------------------------
# Main generator
# ---------------------------------------------------------------------------

def generate(output_path: Path, seed: int, rows: int) -> None:
    rng = random.Random(seed)
    generated_at = datetime.now(timezone.utc).isoformat()
    records: list[dict[str, Any]] = []
    seen_queries: set[str] = set()

    def add_record(query: str, plan: dict[str, Any], default_split: str = "train") -> None:
        norm_query = _normalize_query(query)
        if norm_query in seen_queries:
            return
        seen_queries.add(norm_query)
        tools = [s["tool"] for s in plan.get("steps", [])]
        records.append(
            make_record(
                query=query,
                plan=plan,
                difficulty=_difficulty_for_plan(plan),
                category=categorise(tools),
                split=default_split,
                generated_at=generated_at,
            )
        )

    # Build a large unique pool first.
    passes = max(12, rows // 60)
    for _ in range(passes):
        sub_rng = random.Random(rng.random())

        for queries, plan in build_templates(sub_rng):
            base_query = sub_rng.choice(queries)
            add_record(_style_query(base_query, sub_rng), plan)

        for queries, plan in build_multistep_templates(sub_rng):
            base_query = sub_rng.choice(queries)
            add_record(_style_query(base_query, sub_rng), plan)

        for queries, plan in build_clarify_templates(sub_rng):
            base_query = sub_rng.choice(queries)
            add_record(_style_query(base_query, sub_rng), plan)

    # Ensure every tool appears at least once.
    covered_tools = {tool for r in records for tool in r["meta"]["tools"]}
    missing_tools = sorted(set(TOOL_CATALOG.keys()) - covered_tools)
    for tool_name in missing_tools:
        coverage_rec = _coverage_record_for_tool(tool_name, generated_at, rng)
        query = coverage_rec["messages"][1]["content"]
        plan = json.loads(coverage_rec["messages"][2]["content"])
        add_record(query, plan)

    # Top up if still below target row count.
    refill_attempts = 0
    max_refill_attempts = max(rows * 8, 2000)
    while len(records) < rows and refill_attempts < max_refill_attempts:
        refill_attempts += 1
        sub_rng = random.Random(rng.random())
        picker = sub_rng.randint(0, 2)
        if picker == 0:
            templates = build_templates(sub_rng)
        elif picker == 1:
            templates = build_multistep_templates(sub_rng)
        else:
            templates = build_clarify_templates(sub_rng)

        queries, plan = sub_rng.choice(templates)
        base_query = sub_rng.choice(queries)
        add_record(_style_query(base_query, sub_rng), plan)

    # Assign deterministic split by normalized query hash to avoid leakage.
    train_records: list[dict[str, Any]] = []
    val_records: list[dict[str, Any]] = []
    for rec in records:
        query = rec["messages"][1]["content"]
        split = _split_for_query(query)
        rec["meta"]["split"] = split
        if split == "validation":
            val_records.append(rec)
        else:
            train_records.append(rec)

    # Sample down to requested size while keeping roughly 90/10 split.
    rng.shuffle(train_records)
    rng.shuffle(val_records)
    target_val = max(1, rows // 10)
    target_train = max(1, rows - target_val)

    if len(val_records) < target_val:
        target_train = rows - len(val_records)
        target_val = len(val_records)
    if len(train_records) < target_train:
        target_val = min(len(val_records), rows - len(train_records))
        target_train = len(train_records)

    selected = train_records[:target_train] + val_records[:target_val]
    rng.shuffle(selected)
    all_records = selected[:rows]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as fh:
        for rec in all_records:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    tool_coverage = set()
    multi_count = sum(1 for r in all_records if r["meta"]["is_multi_step"])
    for r in all_records:
        tool_coverage.update(r["meta"]["tools"])

    print(f"Generated {len(all_records)} records → {output_path}")
    print(
        "  Train: "
        f"{sum(1 for r in all_records if r['meta']['split'] == 'train')}  |  "
        "Validation: "
        f"{sum(1 for r in all_records if r['meta']['split'] == 'validation')}"
    )
    print(f"  Multi-step records: {multi_count} ({100 * multi_count // len(all_records)}%)")
    print(f"  Tool coverage: {len(tool_coverage)}/{len(TOOL_CATALOG)} tools")
    cats = {}
    for r in all_records:
        c = r["meta"]["category"]
        cats[c] = cats.get(c, 0) + 1
    for c, cnt in sorted(cats.items(), key=lambda x: -x[1]):
        print(f"    {c}: {cnt}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate Graph workflow fine-tuning dataset")
    parser.add_argument("--output", default="data/graph_workflow_ft_dataset.jsonl",
                        help="Output JSONL path")
    parser.add_argument("--rows", type=int, default=2000, help="Target record count")
    parser.add_argument("--seed", type=int, default=42, help="RNG seed")
    args = parser.parse_args()

    generate(Path(args.output), seed=args.seed, rows=args.rows)
