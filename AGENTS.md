# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## Project Overview

Standalone Microsoft Graph AI agent — a FastAPI service that lets users query and mutate Microsoft 365 / Azure AD (Entra ID) data via natural language. Built on LangGraph with LangChain tools. Decoupled from the broader multi-agent stack (but retains some backward-compat state channels).

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run the server (default port 8090)
uvicorn graph_standalone_app.server:app --host 0.0.0.0 --port 8090 --reload

# Generate synthetic fine-tuning dataset
python scripts/generate_workflow_dataset.py --output data/graph_workflow_ft_dataset.jsonl --seed 42
```

No test suite, linter, or formatter is configured. No Makefile or pyproject.toml.

## Architecture

### Two Execution Modes (`GRAPH_EXECUTION_MODE` env var)

**Classic** (`classic`): Linear pipeline — table_selection → schema → query_gen → execute → response.

**Codemode** (`codemode`): Adds a router (decides if schema needed / multi-step), parallel tool calls, and an evaluator that can loop (up to `GRAPH_CODEMODE_MAX_TURNS`) or finalize.

Both modes are built as LangGraph `StateGraph` workflows in `graph_agent/agent.py`.

### Key Files

- **`graph_agent/agent.py`** (~1030 lines): All LangGraph node functions, workflow builders (`build_classic_workflow`, `build_codemode_workflow`), context compaction, user identifier resolution, tool call guards.
- **`graph_agent/tools.py`** (~2200 lines): 109 `@tool`-decorated functions. All call `make_graph_request()` which handles MSAL token acquisition (thread-safe cache), OData params, retry on 429/5xx.
- **`graph_agent/prompts.py`**: LangChain `ChatPromptTemplate` definitions and Pydantic structured output models.
- **`graph_agent/operations_registry.py`**: Static registry of 69 Graph operations across 12 resource families.
- **`graph_agent/workflow_plan.py`** / **`workflow_executor.py`**: Scaffolding for future fine-tuned model (Qwen 1.5B) that emits structured `WorkflowPlan` DAGs. Not wired into the active workflow yet.
- **`graph_standalone_app/server.py`**: FastAPI app with `/graph/chat`, `/graph/chat/stream`, `/graph/operations`, `/health`.
- **`utils/llm_adapter.py`**: `get_chat_model()` factory supporting `azure_openai`, `nvidia_llama`, `openai_compatible` providers.
- **`utils/agent_utils.py`**: LangGraph `State` TypedDict with annotated channels, `Agents` enum, tool node helpers.

### Important Conventions

- All Graph agent state uses `graph_messages` channel, not `messages`. The `State` TypedDict has channels for other agents (sentinel, opensearch, etc.) retained for backward compat — only `graph_messages` is used here.
- Tool call IDs are truncated to 40 chars (`MAX_TOOL_CALL_ID_LENGTH`).
- If the LLM returns no tool calls when expected, a synthetic `missing_tool_call_guard` is injected and retried up to `MAX_TOOL_RETRIES = 2`.
- Read-only tools (prefixed `get_`, `list_`, `search_`) can run in parallel in codemode; mutating tools (`create_`, `update_`, `delete_`, etc.) always run sequentially.
- User display names are auto-resolved to GUIDs/UPNs via Graph API before tool execution (`_resolve_user_identifier`).
- Context compaction: in codemode, only the last N messages go to the LLM, and `ToolMessage` content is summarized (record count + key identifiers from first 10 records).
- `today_date` (UTC) is injected into prompt state for `{today_date}` template variable.
- All HTTP calls use `httpx` (sync), not `requests` or `aiohttp`.

### API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Liveness check |
| `GET` | `/graph/operations` | List all operation families |
| `GET` | `/graph/operations/{resource_type}` | Ops for one resource |
| `POST` | `/graph/chat` | Synchronous chat |
| `POST` | `/graph/chat/stream` | SSE streaming (runs sync in thread, not token-level streaming) |

Request normalization handles both direct `{"messages": [...]}` and LangServe wrapper `{"input": {"messages": [...]}}` formats.

### Environment

See `.env.example` for all variables. Key ones: `LLM_PROVIDER`, `GRAPH_TENANT_ID`, `GRAPH_CLIENT_ID`, `GRAPH_CLIENT_SECRET`, and provider-specific LLM credentials. Optional `LLM_API_KEY` enables API key gating on all non-health endpoints.
