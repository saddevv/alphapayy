import os


def is_graph_agent_enabled() -> bool:
    """
    Feature flag for enabling/disabling the Microsoft Graph agent.

    - Enable with:  GRAPH_AGENT_ENABLED=true
    - Disable with: GRAPH_AGENT_ENABLED=false
    """
    return os.getenv("GRAPH_AGENT_ENABLED", "true").strip().lower() in {"1", "true", "yes", "y"}


def get_graph_execution_mode() -> str:
    """
    Graph execution mode.

    - classic: existing single-pass workflow
    - codemode: codemode-style router/worker/evaluator workflow
    """
    mode = os.getenv("GRAPH_EXECUTION_MODE", "classic").strip().lower()
    if mode not in {"classic", "codemode"}:
        return "classic"
    return mode


def get_codemode_max_turns() -> int:
    """Maximum codemode execution turns before forcing final response."""
    raw = os.getenv("GRAPH_CODEMODE_MAX_TURNS", "3").strip()
    try:
        value = int(raw)
    except ValueError:
        return 3
    return max(1, min(value, 8))


def get_codemode_context_messages() -> int:
    """How many recent messages to keep for codemode LLM calls."""
    raw = os.getenv("GRAPH_CODEMODE_CONTEXT_MESSAGES", "8").strip()
    try:
        value = int(raw)
    except ValueError:
        return 8
    return max(4, min(value, 20))


def get_codemode_tool_summary_chars() -> int:
    """Max chars retained per tool result for codemode context compression."""
    raw = os.getenv("GRAPH_CODEMODE_TOOL_SUMMARY_CHARS", "1400").strip()
    try:
        value = int(raw)
    except ValueError:
        return 1400
    return max(400, min(value, 12000))


def is_codemode_parallel_reads_enabled() -> bool:
    """Enable parallel execution for read-only tool call batches."""
    return os.getenv("GRAPH_CODEMODE_PARALLEL_READS", "true").strip().lower() in {
        "1",
        "true",
        "yes",
        "y",
    }


def get_graph_config() -> dict:
    """
    Get Microsoft Graph API configuration from environment variables.
    
    Returns:
        dict: Configuration dictionary with tenant_id, client_id, client_secret, and scopes
    """
    return {
        "tenant_id": os.getenv("GRAPH_TENANT_ID", ""),
        "client_id": os.getenv("GRAPH_CLIENT_ID", ""),
        "client_secret": os.getenv("GRAPH_CLIENT_SECRET", ""),
        "scopes": os.getenv(
            "GRAPH_SCOPES",
            "https://graph.microsoft.com/.default"
        ).split(",")
    }
