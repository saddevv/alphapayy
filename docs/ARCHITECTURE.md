# Architecture

## Runtime flow

1. `graph_standalone_app/server.py` receives request.
2. Messages are normalized to LangChain message objects.
3. Request is executed against `graph_agent.agent.graph_graph`.
4. Graph workflow performs:
   - resource/schema decision
   - tool-call generation
   - tool execution
   - final answer synthesis
5. Response returns:
   - `answer`
   - `query_statement`
   - `df` (normalized data)
   - `graph_messages`

## Execution modes

- `classic`: existing schema-select -> query-gen -> execute -> final response flow.
- `codemode`: router -> optional schema-select -> query-gen -> execute -> evaluator -> (continue or finalize).

Codemode mode adds:

- context compaction before planner/evaluator calls (token reduction)
- optional parallel execution for read-only tool call batches
- bounded iterative loop (`GRAPH_CODEMODE_MAX_TURNS`)

## Why this is decoupled

- No supervisor import
- No Sentinel/OpenSearch/MISP/Wazuh routing path
- No chart/correlation agent dependencies
- Single-domain deployment boundary (Microsoft Graph)

## Key packages

- `graph_agent/*` contains Graph logic and operations
- `utils/llm_adapter.py` provides provider abstraction
- `utils/agent_utils.py` provides graph state/typing helpers

## Security boundaries

- API key gate is optional and enforced when `LLM_API_KEY` is set.
- Microsoft Graph credentials are supplied via environment.
- Write actions rely on Graph app permissions and existing tool constraints.
