# Microsoft Graph Agent Standalone (Orphan Branch)

This branch contains a **standalone Microsoft Graph agent application only**.
It is intentionally isolated from the multi-agent supervisor stack.

## Branch model

- Branch: `codex/graph-agent-standalone-only`
- Type: **orphan branch** (no parent commit history)
- Scope: only Graph agent service code and its direct dependencies

## What is included

- Graph workflow engine:
  - `graph_agent/agent.py`
  - `graph_agent/tools.py`
  - `graph_agent/prompts.py`
  - `graph_agent/operations_registry.py`
  - `graph_agent/config.py`
- Standalone HTTP app:
  - `graph_standalone_app/server.py`
- Local utility modules required by Graph engine:
  - `utils/llm_adapter.py`
  - `utils/agent_utils.py`

## Capability parity

This standalone app preserves the same Graph operation layer as the existing integrated Graph agent.

- Graph helper tools defined in `graph_agent/tools.py`: **109** (`@tool` functions)
- Registry-backed Graph operation families: **12**
- Unique registry operations: **69**

Operation families:

- `users` (13)
- `groups` (11)
- `applications` (5)
- `devices` (3)
- `security` (6)
- `attackSimulation` (8)
- `ediscovery` (6)
- `secureScore` (2)
- `threatIndicator` (5)
- `threatSubmission` (3)
- `identitiesHealth` (3)
- `identitiesSensors` (4)

## Run

```bash
pip install -r requirements.txt
uvicorn graph_standalone_app.server:app --host 0.0.0.0 --port 8090 --reload
```

## Docker

Build and run the backend API locally:

```bash
docker build -t graph-agent-standalone:local .
docker run --rm --env-file .env -p 8090:8090 graph-agent-standalone:local
```

Or use Docker Compose:

```bash
docker compose up --build
```

Health check:

```bash
curl http://localhost:8090/health
```

The image runs `graph_standalone_app.server:app` with Uvicorn on port `8090`.
Set `PORT` or `WEB_CONCURRENCY` to override the default container runtime settings.

### Automated image builds

GitHub Actions builds the Docker image on pull requests and pushes to `main`.
For `main` pushes, it publishes to GitHub Container Registry:

```text
ghcr.io/saddevv/alphapayy:latest
ghcr.io/saddevv/alphapayy:sha-<commit>
```

## Execution modes

The Graph agent supports two execution modes:

- `GRAPH_EXECUTION_MODE=classic` (default): original workflow.
- `GRAPH_EXECUTION_MODE=codemode`: codemode-style router/worker/evaluator flow with compact context and iterative evaluation.

Optional codemode tuning:

- `GRAPH_CODEMODE_MAX_TURNS` (default `3`)
- `GRAPH_CODEMODE_CONTEXT_MESSAGES` (default `8`)
- `GRAPH_CODEMODE_TOOL_SUMMARY_CHARS` (default `1400`)
- `GRAPH_CODEMODE_PARALLEL_READS` (default `true`)

## Endpoints

- `GET /health`
- `GET /graph/operations`
- `GET /graph/operations/{resource_type}`
- `POST /graph/chat`
- `POST /graph/chat/stream`

## Environment

Copy `.env.example` and set:

- Graph auth:
  - `GRAPH_TENANT_ID`
  - `GRAPH_CLIENT_ID`
  - `GRAPH_CLIENT_SECRET`
- LLM provider variables based on `LLM_PROVIDER`
- Optional API key gate (`API_KEY_NAME`, `LLM_API_KEY`)

## Documentation

- API contract: `docs/API.md`
- Operation coverage: `docs/OPERATIONS_COVERAGE.md`
- Architecture notes: `docs/ARCHITECTURE.md`
- A2A integration path: `docs/A2A_INTEGRATION_PLAN.md`
- Synthetic dataset generation: `docs/SYNTHETIC_DATASET.md`
