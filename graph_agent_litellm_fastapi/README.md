# Microsoft Graph Agent LiteLLM/FastAPI

This is a low-abstraction, model-agnostic Microsoft Graph agent. It keeps the runtime explicit:
FastAPI receives requests, a small custom agent loop calls LiteLLM, validated tools execute through a
Microsoft Graph client, and the final answer is synthesized from tool results.

## Why This Exists

The original project uses LangGraph and LangChain tools. This version is intentionally flatter:

- no LangChain
- no LangGraph
- no global LLM objects initialized at import time
- no LLM calls inside tools
- no Graph auth inside the agent loop
- no FastAPI imports in business logic

## Architecture

```text
Client
  -> FastAPI routes
  -> ChatService
  -> GraphAgent
  -> LiteLLMClient
  -> ToolExecutor
  -> GraphToolRegistry
  -> GraphClient
  -> Microsoft Graph API
```

## Run

```bash
cp .env.example .env
pip install -e ".[dev]"
uvicorn graph_agent_litellm.app.main:create_app --factory --host 0.0.0.0 --port 8091 --reload
```

## Endpoints

- `GET /health`
- `GET /v1/graph/operations`
- `POST /v1/graph/chat`
- `POST /v1/graph/chat/stream`

## Model Agnostic Config

Set `LLM_MODEL` to any LiteLLM-supported model string. Provider-specific API keys remain the
standard LiteLLM environment variables, for example `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, Azure
OpenAI variables, or a custom `LITELLM_API_BASE`.

## Mutation Safety

Mutating tools are marked with `requires_confirmation`. When
`AGENT_REQUIRE_MUTATION_CONFIRMATION=true`, write operations must include `confirmed=true` in the
tool arguments. This gives the API a clean place to add human approval workflows later.

