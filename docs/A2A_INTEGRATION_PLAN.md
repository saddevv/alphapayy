# A2A Integration Plan

This standalone service is structured to be consumed by an A2A orchestrator later.

## Phase 1: service contract hardening

- Freeze request/response schema for `/graph/chat`.
- Add explicit error codes for auth, Graph API failures, and validation failures.
- Add request id propagation (`thread_id` or external correlation id).

## Phase 2: protocol adapter

- Add an A2A adapter layer that maps protocol envelopes into:
  - `messages`
  - `thread_id`
- Map output payload into A2A response envelopes with deterministic fields.

## Phase 3: policy + guardrails

- Add a write-operation approval policy gate.
- Mark sensitive operations (user updates, deletes, token invalidation) for approval.
- Add allow/deny lists per tenant.

## Phase 4: observability

- Structured logs with request id, operation family, and latency.
- Per-operation success/failure counters.
- Optional trace export.

## Phase 5: deployment boundary

- Containerize this service as an independent unit.
- Keep A2A orchestrator and Graph service deployed separately.
- Use mTLS/API gateway controls between orchestrator and Graph service.
