# API

Base URL example: `http://localhost:8090`

## Health

`GET /health`

Response:

```json
{
  "status": "ok",
  "service": "graph-agent-standalone"
}
```

## List operation coverage

`GET /graph/operations`

Returns supported resources and operation names.

## List operations for one resource

`GET /graph/operations/{resource_type}`

Example:

`GET /graph/operations/users`

## Execute chat

`POST /graph/chat`

Request body (direct form):

```json
{
  "messages": [
    {"role": "user", "content": "Show failed sign-ins for last 7 days"}
  ],
  "thread_id": "user-123"
}
```

Request body (LangServe-like wrapper):

```json
{
  "input": {
    "messages": [
      {"type": "human", "content": "List top risky users"}
    ],
    "user_id": "user-123"
  }
}
```

Response:

```json
{
  "thread_id": "user-123",
  "answer": "...",
  "query_statement": "...",
  "df": [],
  "graph_messages": []
}
```

## Execute chat as SSE

`POST /graph/chat/stream`

Events:

- `result` with final payload
- `done`
- `error` when request fails

## Auth

If `LLM_API_KEY` is set, include header:

- name: `API_KEY_NAME` value (default `x-api-key`)
- value: `LLM_API_KEY`

## Execution mode env

- `GRAPH_EXECUTION_MODE=classic|codemode`
- `GRAPH_CODEMODE_MAX_TURNS` (codemode only)
- `GRAPH_CODEMODE_CONTEXT_MESSAGES` (codemode only)
- `GRAPH_CODEMODE_TOOL_SUMMARY_CHARS` (codemode only)
- `GRAPH_CODEMODE_PARALLEL_READS` (codemode only)
