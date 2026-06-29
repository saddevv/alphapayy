# Architecture

This project is a low-abstraction Microsoft Graph agent. The runtime is organized around explicit
interfaces rather than an agent framework.

## Request Flow

```text
FastAPI route
  -> ChatService
  -> GraphAgent
  -> LiteLLMClient
  -> ToolExecutor
  -> ToolDefinition handler
  -> GraphClient
  -> Microsoft Graph API
```

## Layers

- `app`: FastAPI app construction, routes, dependency accessors.
- `api_models`: Pydantic request/response contracts.
- `services`: Application use cases. Routes delegate here.
- `agent`: The custom agent loop and message normalization policies.
- `llm`: LiteLLM adapter and prompt text.
- `tools`: Tool definitions, registry, validation, and execution policy.
- `graph`: Microsoft Graph auth, HTTP client, and operation catalog.
- `core`: Configuration, error, logging, and API-key helpers.

## Agent Loop

The agent loop does only four things:

1. Send normalized messages and tool schemas to LiteLLM.
2. Execute returned tool calls after validation and policy checks.
3. Append tool results back into the conversation.
4. Stop on a final answer or synthesize one after the max-turn guard.

Read-only tool batches can run concurrently. Mutations always go through confirmation policy and run
through normal validated tool execution.

## Model Agnosticism

The rest of the app depends only on `LiteLLMClient`, not on any vendor SDK. `LLM_MODEL` can point to
OpenAI, Azure OpenAI, Anthropic, Gemini, Ollama, vLLM, or any LiteLLM-supported provider.

## Tool Contract

Each tool has:

- name
- description
- Pydantic args model
- read-only classification
- confirmation requirement
- handler callable

This makes tool schemas, runtime validation, and execution policy testable without an LLM.

