"""
Microsoft Graph API Operations Registry

This module contains a comprehensive registry of all available Microsoft Graph API operations
organized by resource type. Each operation includes:
- HTTP method
- Endpoint pattern
- Description
- Required permissions
- Required/optional parameters
"""

from typing import Dict, Any, List, Optional

# Operation metadata structure
OperationMetadata = Dict[str, Any]

# User Operations
USER_OPERATIONS: Dict[str, OperationMetadata] = {
    "list": {
        "method": "GET",
        "endpoint": "/users",
        "description": "List all users in the organization",
        "permissions": ["User.Read.All", "User.ReadWrite.All"],
        "required_params": [],
        "optional_params": ["$select", "$filter", "$orderby", "$top", "$skip", "$count"],
    },
    "get": {
        "method": "GET",
        "endpoint": "/users/{id}",
        "description": "Get a specific user by ID or userPrincipalName",
        "permissions": ["User.Read.All", "User.ReadWrite.All"],
        "required_params": ["id"],
        "optional_params": ["$select"],
    },
    "create": {
        "method": "POST",
        "endpoint": "/users",
        "description": "Create a new user in the organization",
        "permissions": ["User.ReadWrite.All", "Directory.ReadWrite.All"],
        "required_params": ["accountEnabled", "displayName", "mailNickname", "userPrincipalName", "passwordProfile"],
        "optional_params": ["mail", "jobTitle", "department", "officeLocation", "givenName", "surname"],
        "body_required": True,
    },
    "update": {
        "method": "PATCH",
        "endpoint": "/users/{id}",
        "description": "Update properties of an existing user",
        "permissions": ["User.ReadWrite.All", "Directory.ReadWrite.All"],
        "required_params": ["id"],
        "optional_params": ["displayName", "jobTitle", "department", "officeLocation", "mail", "accountEnabled"],
        "body_required": True,
    },
    "delete": {
        "method": "DELETE",
        "endpoint": "/users/{id}",
        "description": "Delete a user from the organization",
        "permissions": ["User.ReadWrite.All", "Directory.ReadWrite.All"],
        "required_params": ["id"],
        "optional_params": [],
    },
    "getDelta": {
        "method": "GET",
        "endpoint": "/users/delta",
        "description": "Get incremental changes to users (delta query)",
        "permissions": ["User.Read.All", "User.ReadWrite.All", "Directory.Read.All"],
        "required_params": [],
        "optional_params": ["$select", "$filter", "$orderby", "$top", "$skip", "$deltatoken"],
    },
    "changePassword": {
        "method": "POST",
        "endpoint": "/users/{id}/changePassword",
        "description": "Change a user's password",
        "permissions": ["User.ReadWrite.All", "Directory.ReadWrite.All"],
        "required_params": ["id", "currentPassword", "newPassword"],
        "optional_params": [],
        "body_required": True,
    },
    "validatePassword": {
        "method": "POST",
        "endpoint": "/users/{id}/validatePassword",
        "description": "Validate password strength and compliance",
        "permissions": ["User.ReadWrite.All", "Directory.ReadWrite.All"],
        "required_params": ["id", "password"],
        "optional_params": [],
        "body_required": True,
    },
    "retryServiceProvisioning": {
        "method": "POST",
        "endpoint": "/users/{id}/retryServiceProvisioning",
        "description": "Retry service provisioning for a user",
        "permissions": ["User.ReadWrite.All", "Directory.ReadWrite.All"],
        "required_params": ["id"],
        "optional_params": [],
    },
    "convertExternalToInternal": {
        "method": "POST",
        "endpoint": "/users/{id}/convertExternalToInternalMemberUser",
        "description": "Convert an external user to an internal member user",
        "permissions": ["User.ReadWrite.All", "Directory.ReadWrite.All"],
        "required_params": ["id"],
        "optional_params": [],
    },
    "invalidateAllRefreshTokens": {
        "method": "POST",
        "endpoint": "/users/{id}/invalidateAllRefreshTokens",
        "description": "Invalidate all refresh tokens issued to applications for a user",
        "permissions": ["User.ReadWrite.All", "Directory.ReadWrite.All"],
        "required_params": ["id"],
        "optional_params": [],
    },
    "revokeSignInSessions": {
        "method": "POST",
        "endpoint": "/users/{id}/revokeSignInSessions",
        "description": "Revoke all sign-in sessions for a user",
        "permissions": ["User.ReadWrite.All", "Directory.ReadWrite.All"],
        "required_params": ["id"],
        "optional_params": [],
    },
    "exportPersonalData": {
        "method": "POST",
        "endpoint": "/users/{id}/exportPersonalData",
        "description": "Export a user's personal data for compliance",
        "permissions": ["User.ReadWrite.All", "Directory.ReadWrite.All"],
        "required_params": ["id", "storageLocation"],
        "optional_params": [],
        "body_required": True,
    },
}

# Group Operations
GROUP_OPERATIONS: Dict[str, OperationMetadata] = {
    "list": {
        "method": "GET",
        "endpoint": "/groups",
        "description": "List all groups in the organization",
        "permissions": ["Group.Read.All", "Group.ReadWrite.All"],
        "required_params": [],
        "optional_params": ["$select", "$filter", "$orderby", "$top", "$skip"],
    },
    "get": {
        "method": "GET",
        "endpoint": "/groups/{id}",
        "description": "Get a specific group by ID",
        "permissions": ["Group.Read.All", "Group.ReadWrite.All"],
        "required_params": ["id"],
        "optional_params": ["$select"],
    },
    "create": {
        "method": "POST",
        "endpoint": "/groups",
        "description": "Create a new group",
        "permissions": ["Group.ReadWrite.All", "Directory.ReadWrite.All"],
        "required_params": ["displayName", "mailEnabled", "securityEnabled", "mailNickname"],
        "optional_params": ["description", "groupTypes"],
        "body_required": True,
    },
    "update": {
        "method": "PATCH",
        "endpoint": "/groups/{id}",
        "description": "Update properties of an existing group",
        "permissions": ["Group.ReadWrite.All", "Directory.ReadWrite.All"],
        "required_params": ["id"],
        "optional_params": ["displayName", "description"],
        "body_required": True,
    },
    "delete": {
        "method": "DELETE",
        "endpoint": "/groups/{id}",
        "description": "Delete a group",
        "permissions": ["Group.ReadWrite.All", "Directory.ReadWrite.All"],
        "required_params": ["id"],
        "optional_params": [],
    },
    "addMember": {
        "method": "POST",
        "endpoint": "/groups/{id}/members/$ref",
        "description": "Add a member (user or group) to a group",
        "permissions": ["Group.ReadWrite.All", "Directory.ReadWrite.All"],
        "required_params": ["id", "memberId"],
        "optional_params": [],
        "body_required": True,
    },
    "removeMember": {
        "method": "DELETE",
        "endpoint": "/groups/{id}/members/{memberId}/$ref",
        "description": "Remove a member from a group",
        "permissions": ["Group.ReadWrite.All", "Directory.ReadWrite.All"],
        "required_params": ["id", "memberId"],
        "optional_params": [],
    },
    "addOwner": {
        "method": "POST",
        "endpoint": "/groups/{id}/owners/$ref",
        "description": "Add an owner to a group",
        "permissions": ["Group.ReadWrite.All", "Directory.ReadWrite.All"],
        "required_params": ["id", "ownerId"],
        "optional_params": [],
        "body_required": True,
    },
    "removeOwner": {
        "method": "DELETE",
        "endpoint": "/groups/{id}/owners/{ownerId}/$ref",
        "description": "Remove an owner from a group",
        "permissions": ["Group.ReadWrite.All", "Directory.ReadWrite.All"],
        "required_params": ["id", "ownerId"],
        "optional_params": [],
    },
    "listMembers": {
        "method": "GET",
        "endpoint": "/groups/{id}/members",
        "description": "List all members of a group",
        "permissions": ["Group.Read.All", "Group.ReadWrite.All"],
        "required_params": ["id"],
        "optional_params": ["$select", "$top"],
    },
    "listOwners": {
        "method": "GET",
        "endpoint": "/groups/{id}/owners",
        "description": "List all owners of a group",
        "permissions": ["Group.Read.All", "Group.ReadWrite.All"],
        "required_params": ["id"],
        "optional_params": ["$select", "$top"],
    },
}

# Application Operations
APPLICATION_OPERATIONS: Dict[str, OperationMetadata] = {
    "list": {
        "method": "GET",
        "endpoint": "/applications",
        "description": "List all applications",
        "permissions": ["Application.Read.All", "Application.ReadWrite.All"],
        "required_params": [],
        "optional_params": ["$select", "$filter", "$top"],
    },
    "get": {
        "method": "GET",
        "endpoint": "/applications/{id}",
        "description": "Get a specific application by ID",
        "permissions": ["Application.Read.All", "Application.ReadWrite.All"],
        "required_params": ["id"],
        "optional_params": ["$select"],
    },
    "create": {
        "method": "POST",
        "endpoint": "/applications",
        "description": "Create a new application",
        "permissions": ["Application.ReadWrite.All"],
        "required_params": ["displayName"],
        "optional_params": ["web", "spa", "publicClient"],
        "body_required": True,
    },
    "update": {
        "method": "PATCH",
        "endpoint": "/applications/{id}",
        "description": "Update an application",
        "permissions": ["Application.ReadWrite.All"],
        "required_params": ["id"],
        "optional_params": ["displayName", "web", "spa"],
        "body_required": True,
    },
    "delete": {
        "method": "DELETE",
        "endpoint": "/applications/{id}",
        "description": "Delete an application",
        "permissions": ["Application.ReadWrite.All"],
        "required_params": ["id"],
        "optional_params": [],
    },
}

# Device Operations
DEVICE_OPERATIONS: Dict[str, OperationMetadata] = {
    "list": {
        "method": "GET",
        "endpoint": "/devices",
        "description": "List all devices",
        "permissions": ["Device.Read.All", "Directory.Read.All"],
        "required_params": [],
        "optional_params": ["$select", "$filter", "$top"],
    },
    "get": {
        "method": "GET",
        "endpoint": "/devices/{id}",
        "description": "Get a specific device by ID",
        "permissions": ["Device.Read.All", "Directory.Read.All"],
        "required_params": ["id"],
        "optional_params": ["$select"],
    },
    "delete": {
        "method": "DELETE",
        "endpoint": "/devices/{id}",
        "description": "Delete a device",
        "permissions": ["Device.ReadWrite.All", "Directory.ReadWrite.All"],
        "required_params": ["id"],
        "optional_params": [],
    },
}

# Security Operations (extending existing)
SECURITY_OPERATIONS: Dict[str, OperationMetadata] = {
    "listAlerts": {
        "method": "GET",
        "endpoint": "/security/alerts_v2",
        "description": "List security alerts",
        "permissions": ["SecurityEvents.Read.All", "SecurityEvents.ReadWrite.All"],
        "required_params": [],
        "optional_params": ["$select", "$filter", "$top", "$count", "$skip"],
    },
    "getAlert": {
        "method": "GET",
        "endpoint": "/security/alerts_v2/{id}",
        "description": "Get a specific security alert",
        "permissions": ["SecurityEvents.Read.All", "SecurityEvents.ReadWrite.All"],
        "required_params": ["id"],
        "optional_params": ["$select"],
    },
    "updateAlert": {
        "method": "PATCH",
        "endpoint": "/security/alerts_v2/{id}",
        "description": "Update a security alert",
        "permissions": ["SecurityEvents.ReadWrite.All"],
        "required_params": ["id"],
        "optional_params": ["status", "assignedTo"],
        "body_required": True,
    },
    "listIncidents": {
        "method": "GET",
        "endpoint": "/security/incidents",
        "description": "List security incidents",
        "permissions": ["SecurityIncidents.Read.All", "SecurityIncidents.ReadWrite.All"],
        "required_params": [],
        "optional_params": ["$select", "$filter", "$top"],
    },
    "getIncident": {
        "method": "GET",
        "endpoint": "/security/incidents/{id}",
        "description": "Get a specific security incident",
        "permissions": ["SecurityIncidents.Read.All", "SecurityIncidents.ReadWrite.All"],
        "required_params": ["id"],
        "optional_params": ["$select"],
    },
    "updateIncident": {
        "method": "PATCH",
        "endpoint": "/security/incidents/{id}",
        "description": "Update a security incident",
        "permissions": ["SecurityIncidents.ReadWrite.All"],
        "required_params": ["id"],
        "optional_params": ["status", "assignedTo"],
        "body_required": True,
    },
}

# Attack Simulation Operations
ATTACK_SIMULATION_OPERATIONS: Dict[str, OperationMetadata] = {
    "listSimulations": {
        "method": "GET",
        "endpoint": "/security/attackSimulation/simulations",
        "description": "List attack simulation simulations",
        "permissions": ["AttackSimulation.Read.All", "AttackSimulation.ReadWrite.All"],
        "required_params": [],
        "optional_params": ["$select", "$filter", "$top", "$skip"],
    },
    "createSimulation": {
        "method": "POST",
        "endpoint": "/security/attackSimulation/simulations",
        "description": "Create a new attack simulation",
        "permissions": ["AttackSimulation.ReadWrite.All"],
        "required_params": [],
        "optional_params": ["displayName", "description", "payload", "loginPage", "landingPage"],
        "body_required": True,
    },
    "getSimulation": {
        "method": "GET",
        "endpoint": "/security/attackSimulation/simulations/{id}",
        "description": "Get a specific attack simulation",
        "permissions": ["AttackSimulation.Read.All", "AttackSimulation.ReadWrite.All"],
        "required_params": ["id"],
        "optional_params": ["$select"],
    },
    "updateSimulation": {
        "method": "PATCH",
        "endpoint": "/security/attackSimulation/simulations/{id}",
        "description": "Update an attack simulation",
        "permissions": ["AttackSimulation.ReadWrite.All"],
        "required_params": ["id"],
        "optional_params": ["displayName", "description", "status"],
        "body_required": True,
    },
    "deleteSimulation": {
        "method": "DELETE",
        "endpoint": "/security/attackSimulation/simulations/{id}",
        "description": "Delete an attack simulation",
        "permissions": ["AttackSimulation.ReadWrite.All"],
        "required_params": ["id"],
        "optional_params": [],
    },
    "getPayload": {
        "method": "GET",
        "endpoint": "/security/attackSimulation/simulations/{id}/payload",
        "description": "Get payload for a simulation",
        "permissions": ["AttackSimulation.Read.All", "AttackSimulation.ReadWrite.All"],
        "required_params": ["id"],
        "optional_params": ["$select"],
    },
    "getLoginPage": {
        "method": "GET",
        "endpoint": "/security/attackSimulation/simulations/{id}/loginPage",
        "description": "Get login page for a simulation",
        "permissions": ["AttackSimulation.Read.All", "AttackSimulation.ReadWrite.All"],
        "required_params": ["id"],
        "optional_params": ["$select"],
    },
    "getLandingPage": {
        "method": "GET",
        "endpoint": "/security/attackSimulation/simulations/{id}/landingPage",
        "description": "Get landing page for a simulation",
        "permissions": ["AttackSimulation.Read.All", "AttackSimulation.ReadWrite.All"],
        "required_params": ["id"],
        "optional_params": ["$select"],
    },
}

# eDiscovery Operations
EDISCOVERY_OPERATIONS: Dict[str, OperationMetadata] = {
    "listCases": {
        "method": "GET",
        "endpoint": "/security/cases/ediscoveryCases",
        "description": "List eDiscovery cases",
        "permissions": ["eDiscovery.Read.All", "eDiscovery.ReadWrite.All"],
        "required_params": [],
        "optional_params": ["$select", "$filter", "$top", "$skip"],
    },
    "getCase": {
        "method": "GET",
        "endpoint": "/security/cases/ediscoveryCases/{id}",
        "description": "Get a specific eDiscovery case",
        "permissions": ["eDiscovery.Read.All", "eDiscovery.ReadWrite.All"],
        "required_params": ["id"],
        "optional_params": ["$select"],
    },
    "createCase": {
        "method": "POST",
        "endpoint": "/security/cases/ediscoveryCases",
        "description": "Create a new eDiscovery case",
        "permissions": ["eDiscovery.ReadWrite.All"],
        "required_params": ["displayName"],
        "optional_params": ["description"],
        "body_required": True,
    },
    "updateCase": {
        "method": "PATCH",
        "endpoint": "/security/cases/ediscoveryCases/{id}",
        "description": "Update an eDiscovery case",
        "permissions": ["eDiscovery.ReadWrite.All"],
        "required_params": ["id"],
        "optional_params": ["displayName", "description", "status"],
        "body_required": True,
    },
    "deleteCase": {
        "method": "DELETE",
        "endpoint": "/security/cases/ediscoveryCases/{id}",
        "description": "Delete an eDiscovery case",
        "permissions": ["eDiscovery.ReadWrite.All"],
        "required_params": ["id"],
        "optional_params": [],
    },
    "listCaseOperations": {
        "method": "GET",
        "endpoint": "/security/cases/ediscoveryCases/{id}/operations",
        "description": "List operations for an eDiscovery case",
        "permissions": ["eDiscovery.Read.All", "eDiscovery.ReadWrite.All"],
        "required_params": ["id"],
        "optional_params": ["$select", "$top"],
    },
}

# Secure Score Operations
SECURE_SCORE_OPERATIONS: Dict[str, OperationMetadata] = {
    "listSecureScores": {
        "method": "GET",
        "endpoint": "/security/secureScores",
        "description": "List secure scores",
        "permissions": ["SecurityEvents.Read.All", "SecurityEvents.ReadWrite.All"],
        "required_params": [],
        "optional_params": ["$select", "$filter", "$top"],
    },
    "getSecureScore": {
        "method": "GET",
        "endpoint": "/security/secureScores/{id}",
        "description": "Get a specific secure score",
        "permissions": ["SecurityEvents.Read.All", "SecurityEvents.ReadWrite.All"],
        "required_params": ["id"],
        "optional_params": ["$select"],
    },
    "listSecureScoreControlProfiles": {
        "method": "GET",
        "endpoint": "/security/secureScoreControlProfiles",
        "description": "List secure score control profiles",
        "permissions": ["SecurityEvents.Read.All", "SecurityEvents.ReadWrite.All"],
        "required_params": [],
        "optional_params": ["$select", "$filter", "$top"],
    },
    "getSecureScoreControlProfile": {
        "method": "GET",
        "endpoint": "/security/secureScoreControlProfiles/{id}",
        "description": "Get a specific secure score control profile",
        "permissions": ["SecurityEvents.Read.All", "SecurityEvents.ReadWrite.All"],
        "required_params": ["id"],
        "optional_params": ["$select"],
    },
    "updateSecureScoreControlProfile": {
        "method": "PATCH",
        "endpoint": "/security/secureScoreControlProfiles/{id}",
        "description": "Update a secure score control profile",
        "permissions": ["SecurityEvents.ReadWrite.All"],
        "required_params": ["id"],
        "optional_params": ["controlStateUpdates"],
        "body_required": True,
    },
}

# Threat Submission Operations
THREAT_SUBMISSION_OPERATIONS: Dict[str, OperationMetadata] = {
    "listSubmissions": {
        "method": "GET",
        "endpoint": "/security/threatSubmission/submissions",
        "description": "List threat submissions",
        "permissions": ["ThreatSubmission.Read.All", "ThreatSubmission.ReadWrite.All"],
        "required_params": [],
        "optional_params": ["$select", "$filter", "$top"],
    },
    "getSubmission": {
        "method": "GET",
        "endpoint": "/security/threatSubmission/submissions/{id}",
        "description": "Get a specific threat submission",
        "permissions": ["ThreatSubmission.Read.All", "ThreatSubmission.ReadWrite.All"],
        "required_params": ["id"],
        "optional_params": ["$select"],
    },
    "createSubmission": {
        "method": "POST",
        "endpoint": "/security/threatSubmission/submissions",
        "description": "Create a new threat submission",
        "permissions": ["ThreatSubmission.ReadWrite.All"],
        "required_params": [],
        "optional_params": ["category", "contentType", "source", "value"],
        "body_required": True,
    },
}

# Attack Simulation Operations
ATTACK_SIMULATION_OPERATIONS: Dict[str, OperationMetadata] = {
    "listSimulations": {
        "method": "GET",
        "endpoint": "/security/attackSimulation/simulations",
        "description": "List attack simulation simulations",
        "permissions": ["AttackSimulation.Read.All", "AttackSimulation.ReadWrite.All"],
        "required_params": [],
        "optional_params": ["$select", "$filter", "$top", "$skip"],
    },
    "createSimulation": {
        "method": "POST",
        "endpoint": "/security/attackSimulation/simulations",
        "description": "Create a new attack simulation",
        "permissions": ["AttackSimulation.ReadWrite.All"],
        "required_params": [],
        "optional_params": ["displayName", "description", "payload", "loginPage", "landingPage"],
        "body_required": True,
    },
    "getSimulation": {
        "method": "GET",
        "endpoint": "/security/attackSimulation/simulations/{id}",
        "description": "Get a specific attack simulation",
        "permissions": ["AttackSimulation.Read.All", "AttackSimulation.ReadWrite.All"],
        "required_params": ["id"],
        "optional_params": ["$select"],
    },
    "updateSimulation": {
        "method": "PATCH",
        "endpoint": "/security/attackSimulation/simulations/{id}",
        "description": "Update an attack simulation",
        "permissions": ["AttackSimulation.ReadWrite.All"],
        "required_params": ["id"],
        "optional_params": ["displayName", "description", "status"],
        "body_required": True,
    },
    "deleteSimulation": {
        "method": "DELETE",
        "endpoint": "/security/attackSimulation/simulations/{id}",
        "description": "Delete an attack simulation",
        "permissions": ["AttackSimulation.ReadWrite.All"],
        "required_params": ["id"],
        "optional_params": [],
    },
    "getPayload": {
        "method": "GET",
        "endpoint": "/security/attackSimulation/simulations/{id}/payload",
        "description": "Get payload for a simulation",
        "permissions": ["AttackSimulation.Read.All", "AttackSimulation.ReadWrite.All"],
        "required_params": ["id"],
        "optional_params": ["$select"],
    },
    "getLoginPage": {
        "method": "GET",
        "endpoint": "/security/attackSimulation/simulations/{id}/loginPage",
        "description": "Get login page for a simulation",
        "permissions": ["AttackSimulation.Read.All", "AttackSimulation.ReadWrite.All"],
        "required_params": ["id"],
        "optional_params": ["$select"],
    },
    "getLandingPage": {
        "method": "GET",
        "endpoint": "/security/attackSimulation/simulations/{id}/landingPage",
        "description": "Get landing page for a simulation",
        "permissions": ["AttackSimulation.Read.All", "AttackSimulation.ReadWrite.All"],
        "required_params": ["id"],
        "optional_params": ["$select"],
    },
}

# eDiscovery Operations
EDISCOVERY_OPERATIONS: Dict[str, OperationMetadata] = {
    "listCases": {
        "method": "GET",
        "endpoint": "/security/cases/ediscoveryCases",
        "description": "List eDiscovery cases",
        "permissions": ["eDiscovery.Read.All", "eDiscovery.ReadWrite.All"],
        "required_params": [],
        "optional_params": ["$select", "$filter", "$top", "$skip"],
    },
    "getCase": {
        "method": "GET",
        "endpoint": "/security/cases/ediscoveryCases/{id}",
        "description": "Get a specific eDiscovery case",
        "permissions": ["eDiscovery.Read.All", "eDiscovery.ReadWrite.All"],
        "required_params": ["id"],
        "optional_params": ["$select"],
    },
    "createCase": {
        "method": "POST",
        "endpoint": "/security/cases/ediscoveryCases",
        "description": "Create a new eDiscovery case",
        "permissions": ["eDiscovery.ReadWrite.All"],
        "required_params": ["displayName"],
        "optional_params": ["description"],
        "body_required": True,
    },
    "updateCase": {
        "method": "PATCH",
        "endpoint": "/security/cases/ediscoveryCases/{id}",
        "description": "Update an eDiscovery case",
        "permissions": ["eDiscovery.ReadWrite.All"],
        "required_params": ["id"],
        "optional_params": ["displayName", "description", "status"],
        "body_required": True,
    },
    "deleteCase": {
        "method": "DELETE",
        "endpoint": "/security/cases/ediscoveryCases/{id}",
        "description": "Delete an eDiscovery case",
        "permissions": ["eDiscovery.ReadWrite.All"],
        "required_params": ["id"],
        "optional_params": [],
    },
    "listCaseOperations": {
        "method": "GET",
        "endpoint": "/security/cases/ediscoveryCases/{id}/operations",
        "description": "List operations for an eDiscovery case",
        "permissions": ["eDiscovery.Read.All", "eDiscovery.ReadWrite.All"],
        "required_params": ["id"],
        "optional_params": ["$select", "$top"],
    },
}

# Secure Score Operations
SECURE_SCORE_OPERATIONS: Dict[str, OperationMetadata] = {
    "listSecureScores": {
        "method": "GET",
        "endpoint": "/security/secureScores",
        "description": "List secure scores",
        "permissions": ["SecurityEvents.Read.All", "SecurityEvents.ReadWrite.All"],
        "required_params": [],
        "optional_params": ["$select", "$filter", "$top"],
    },
    "listSecureScoreControlProfiles": {
        "method": "GET",
        "endpoint": "/security/secureScoreControlProfiles",
        "description": "List secure score control profiles",
        "permissions": ["SecurityEvents.Read.All", "SecurityEvents.ReadWrite.All"],
        "required_params": [],
        "optional_params": ["$select", "$filter", "$top"],
    },
}

# Threat Intelligence Operations
THREAT_INTELLIGENCE_INDICATORS_OPERATIONS: Dict[str, OperationMetadata] = {
    "listIndicators": {
        "method": "GET",
        "endpoint": "/security/tiIndicators",
        "description": "List threat intelligence indicators",
        "permissions": ["ThreatIndicators.Read.All", "ThreatIndicators.ReadWrite.All"],
        "required_params": [],
        "optional_params": ["$select", "$filter", "$top", "$skip"],
    },
    "getIndicator": {
        "method": "GET",
        "endpoint": "/security/tiIndicators/{id}",
        "description": "Get a specific threat intelligence indicator",
        "permissions": ["ThreatIndicators.Read.All", "ThreatIndicators.ReadWrite.All"],
        "required_params": ["id"],
        "optional_params": ["$select"],
    },
    "createIndicator": {
        "method": "POST",
        "endpoint": "/security/tiIndicators",
        "description": "Create a new threat intelligence indicator",
        "permissions": ["ThreatIndicators.ReadWrite.All"],
        "required_params": [],
        "optional_params": ["targetProduct", "indicator", "action", "description"],
        "body_required": True,
    },
    "updateIndicator": {
        "method": "PATCH",
        "endpoint": "/security/tiIndicators/{id}",
        "description": "Update a threat intelligence indicator",
        "permissions": ["ThreatIndicators.ReadWrite.All"],
        "required_params": ["id"],
        "optional_params": ["action", "description", "expirationDateTime"],
        "body_required": True,
    },
    "deleteIndicator": {
        "method": "DELETE",
        "endpoint": "/security/tiIndicators/{id}",
        "description": "Delete a threat intelligence indicator",
        "permissions": ["ThreatIndicators.ReadWrite.All"],
        "required_params": ["id"],
        "optional_params": [],
    },
}

IDENTITIES_HEALTH_OPERATIONS: Dict[str, OperationMetadata] = {
    "listHealthIssues": {
        "method": "GET",
        "endpoint": "/security/identities/healthIssues",
        "description": "List identities health issues",
        "permissions": ["SecurityIdentitiesHealth.Read.All"],
        "required_params": [],
        "optional_params": ["$select", "$filter", "$top"],
    },
    "getHealthIssue": {
        "method": "GET",
        "endpoint": "/security/identities/healthIssues/{id}",
        "description": "Get a specific identities health issue",
        "permissions": ["SecurityIdentitiesHealth.Read.All"],
        "required_params": ["id"],
        "optional_params": ["$select"],
    },
    "updateHealthIssue": {
        "method": "PATCH",
        "endpoint": "/security/identities/healthIssues/{id}",
        "description": "Update a specific identities health issue",
        "permissions": ["SecurityIdentitiesHealth.ReadWrite.All"],
        "required_params": ["id"],
        "optional_params": ["status"],
        "body_required": True,
    },
}

IDENTITIES_SENSOR_OPERATIONS: Dict[str, OperationMetadata] = {
    "listSensors": {
        "method": "GET",
        "endpoint": "/security/identities/sensors",
        "description": "List identities sensors",
        "permissions": ["SecurityIdentitiesSensors.Read.All"],
        "required_params": [],
        "optional_params": ["$count", "$select", "$filter", "$top"],
    },
    "getSensor": {
        "method": "GET",
        "endpoint": "/security/identities/sensors/{id}",
        "description": "Get a specific identities sensor",
        "permissions": ["SecurityIdentitiesSensors.Read.All"],
        "required_params": ["id"],
        "optional_params": ["$select"],
    },
    "updateSensor": {
        "method": "PATCH",
        "endpoint": "/security/identities/sensors/{id}",
        "description": "Update a specific identities sensor",
        "permissions": ["SecurityIdentitiesSensors.Read.All"],
        "required_params": ["id"],
        "optional_params": ["status"],
        "body_required": True,
    },
    "deleteSensor": {
        "method": "DELETE",
        "endpoint": "/security/identities/sensors/{id}",
        "description": "Delete a specific identities sensor",
        "permissions": ["SecurityIdentitiesSensors.Read.All"],
        "required_params": ["id"],
        "optional_params": [],
    },
}

# Master registry mapping resource types to their operations
OPERATIONS_REGISTRY: Dict[str, Dict[str, OperationMetadata]] = {
    "users": USER_OPERATIONS,
    "user": USER_OPERATIONS,
    "groups": GROUP_OPERATIONS,
    "group": GROUP_OPERATIONS,
    "applications": APPLICATION_OPERATIONS,
    "application": APPLICATION_OPERATIONS,
    "devices": DEVICE_OPERATIONS,
    "device": DEVICE_OPERATIONS,
    "security": SECURITY_OPERATIONS,
    "alerts": SECURITY_OPERATIONS,
    "incidents": SECURITY_OPERATIONS,
    "attackSimulation": ATTACK_SIMULATION_OPERATIONS,
    "simulation": ATTACK_SIMULATION_OPERATIONS,
    "ediscovery": EDISCOVERY_OPERATIONS,
    "ediscoveryCase": EDISCOVERY_OPERATIONS,
    "secureScore": SECURE_SCORE_OPERATIONS,
    "secureScores": SECURE_SCORE_OPERATIONS,
    "threatIndicator": THREAT_INTELLIGENCE_INDICATORS_OPERATIONS,
    "threatIndicators": THREAT_INTELLIGENCE_INDICATORS_OPERATIONS,
    "threatSubmission": THREAT_SUBMISSION_OPERATIONS,
    "threatSubmissions": THREAT_SUBMISSION_OPERATIONS,
    "identitiesHealth": IDENTITIES_HEALTH_OPERATIONS,
    "identityHealth": IDENTITIES_HEALTH_OPERATIONS,
    "identitiesSensors": IDENTITIES_SENSOR_OPERATIONS,
    "identitySensors": IDENTITIES_SENSOR_OPERATIONS,
}


def get_operation(resource_type: str, operation_name: str) -> Optional[OperationMetadata]:
    """
    Get operation metadata for a specific resource and operation.
    
    Args:
        resource_type: The resource type (e.g., "users", "groups")
        operation_name: The operation name (e.g., "create", "update", "delete")
    
    Returns:
        OperationMetadata dict or None if not found
    """
    resource_type_lower = resource_type.lower()
    if resource_type_lower not in OPERATIONS_REGISTRY:
        return None
    
    operations = OPERATIONS_REGISTRY[resource_type_lower]
    operation_name_lower = operation_name.lower()
    
    # Try exact match first
    if operation_name_lower in operations:
        return operations[operation_name_lower]
    
    # Try case-insensitive match
    for op_name, op_meta in operations.items():
        if op_name.lower() == operation_name_lower:
            return op_meta
    
    return None


def list_resource_operations(resource_type: str) -> List[Dict[str, Any]]:
    """
    List all available operations for a resource type.
    
    Args:
        resource_type: The resource type (e.g., "users", "groups")
    
    Returns:
        List of operation metadata dictionaries
    """
    resource_type_lower = resource_type.lower()
    if resource_type_lower not in OPERATIONS_REGISTRY:
        return []
    
    operations = OPERATIONS_REGISTRY[resource_type_lower]
    return [
        {
            "name": op_name,
            **op_meta
        }
        for op_name, op_meta in operations.items()
    ]


def list_all_resources() -> List[str]:
    """
    List all resource types that have registered operations.
    
    Returns:
        List of resource type names
    """
    # Return unique resource types (excluding aliases)
    unique_resources = set()
    for resource_type in OPERATIONS_REGISTRY.keys():
        # Skip aliases (lowercase single word)
        if resource_type not in [
            "user",
            "group",
            "application",
            "device",
            "simulation",
            "ediscoveryCase",
            "secureScores",
            "threatIndicators",
            "threatSubmissions",
            "identityHealth",
            "identitySensors",
        ]:
            unique_resources.add(resource_type)
    return sorted(list(unique_resources))

