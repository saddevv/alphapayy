"""Plan-based workflow executor for the Qwen 1.5B fine-tuned model.

Architecture overview
---------------------
The new request path looks like this::

    User query
        │
        ▼
    Qwen 1.5B ──► WorkflowPlan (JSON)
        │
        ▼ (validate)
    WorkflowValidator ──► fallback to large LLM if invalid / low-confidence
        │
        ▼ (execute)
    WorkflowExecutor ──► runs steps in dependency order,
                          resolves $step_id.field references,
                          collects tool results
        │
        ▼
    large LLM (GPT-4o / Nemotron) ──► final human-readable answer

This module provides:
- ``WorkflowExecutor``: executes a validated WorkflowPlan and returns all
  tool results keyed by step_id.
- ``execute_plan_with_fallback``: top-level helper that validates the plan,
  falls back to the existing LangGraph workflow if validation fails, and
  returns a unified result dict.
"""
from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from graph_agent.workflow_plan import (
    WorkflowPlan,
    WorkflowStep,
    WorkflowValidator,
    resolve_step_references,
)

logger = logging.getLogger(__name__)

#: Minimum confidence score below which the plan is treated as unreliable
#: and the fallback large-LLM path is used instead.
MIN_CONFIDENCE_THRESHOLD = 0.6

#: Read-only tool name prefixes — these are safe to parallelise.
_READ_PREFIXES = ("get_", "list_", "search_")
_MUTATING_PREFIXES = (
    "create_", "update_", "delete_", "change_", "set_", "reset_",
    "revoke_", "invalidate_", "export_", "convert_", "retry_",
    "add_", "remove_", "disable_", "wipe_", "retire_", "remote_",
    "sync_", "rename_",
)


def _is_read_only(tool_name: str) -> bool:
    return tool_name.startswith(_READ_PREFIXES) and not tool_name.startswith(_MUTATING_PREFIXES)


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------

class WorkflowExecutor:
    """Execute a validated WorkflowPlan step by step.

    Dependency ordering is respected: steps whose ``depends_on`` list is
    empty (or already satisfied) are eligible to run.  Read-only steps that
    are ready at the same time are executed in parallel (up to
    ``max_workers`` threads).

    Args:
        tool_map: Mapping of tool name → callable (langchain ``@tool``).
        max_workers: Maximum parallel threads for read-only batches.
    """

    def __init__(self, tool_map: dict[str, Any], max_workers: int = 4) -> None:
        self._tool_map = tool_map
        self._max_workers = max_workers

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def execute(self, plan: WorkflowPlan) -> dict[str, Any]:
        """Run all steps and return a mapping of step_id → tool result.

        Raises:
            RuntimeError: If a step fails and no retry is possible.
        """
        completed: dict[str, Any] = {}   # step_id → raw tool result (parsed JSON)
        pending = list(plan.steps)

        while pending:
            ready = self._find_ready_steps(pending, completed)
            if not ready:
                remaining_ids = [s.step_id for s in pending]
                raise RuntimeError(
                    f"No steps are ready to execute; possible cycle or missing dep. "
                    f"Remaining: {remaining_ids}"
                )

            # Split ready steps into read-only (parallelisable) and mutating
            read_steps = [s for s in ready if _is_read_only(s.tool)]
            write_steps = [s for s in ready if not _is_read_only(s.tool)]

            # Run read-only steps in parallel
            if len(read_steps) > 1:
                batch_results = self._run_parallel(read_steps, completed)
            elif read_steps:
                batch_results = {read_steps[0].step_id: self._run_step(read_steps[0], completed)}
            else:
                batch_results = {}

            # Run mutating steps sequentially (order within batch is insertion order)
            for step in write_steps:
                batch_results[step.step_id] = self._run_step(step, completed)

            completed.update(batch_results)
            executed_ids = set(batch_results.keys())
            pending = [s for s in pending if s.step_id not in executed_ids]

        return completed

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _find_ready_steps(
        self,
        pending: list[WorkflowStep],
        completed: dict[str, Any],
    ) -> list[WorkflowStep]:
        """Return steps whose dependencies have all completed."""
        return [s for s in pending if all(dep in completed for dep in s.depends_on)]

    def _run_parallel(
        self,
        steps: list[WorkflowStep],
        completed: dict[str, Any],
    ) -> dict[str, Any]:
        results: dict[str, Any] = {}
        with ThreadPoolExecutor(max_workers=min(self._max_workers, len(steps))) as pool:
            future_to_step = {
                pool.submit(self._run_step, step, completed): step
                for step in steps
            }
            for future in as_completed(future_to_step):
                step = future_to_step[future]
                try:
                    results[step.step_id] = future.result()
                except Exception as exc:
                    logger.error("Parallel step '%s' failed: %s", step.step_id, exc)
                    results[step.step_id] = {"error": {"message": str(exc)}}
        return results

    def _run_step(
        self,
        step: WorkflowStep,
        completed: dict[str, Any],
    ) -> Any:
        """Resolve references, invoke the tool, and return the parsed result."""
        logger.debug("Executing plan step '%s' → tool '%s'", step.step_id, step.tool)

        tool_func = self._tool_map.get(step.tool)
        if tool_func is None:
            raise RuntimeError(f"Tool '{step.tool}' not found in tool map.")

        try:
            resolved_args = resolve_step_references(step.args, completed)
        except (KeyError, ValueError) as exc:
            raise RuntimeError(
                f"Step '{step.step_id}': failed to resolve references: {exc}"
            ) from exc

        try:
            raw = tool_func.invoke(resolved_args)
        except Exception as exc:
            logger.error("Tool '%s' raised: %s", step.tool, exc)
            return {"error": {"message": str(exc)}}

        # Tools return JSON strings; parse them so downstream steps can index fields
        if isinstance(raw, str):
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return {"raw": raw}
        return raw


# ---------------------------------------------------------------------------
# Top-level helper with confidence-based fallback
# ---------------------------------------------------------------------------

def execute_plan_with_fallback(
    plan: WorkflowPlan,
    tool_map: dict[str, Any],
    fallback_fn: Any,          # callable(state) → dict  (the existing LangGraph node)
    state: dict[str, Any],
    confidence_threshold: float = MIN_CONFIDENCE_THRESHOLD,
    max_workers: int = 4,
) -> dict[str, Any]:
    """Validate and execute *plan*, falling back to *fallback_fn* when needed.

    Args:
        plan: The WorkflowPlan emitted by Qwen 1.5B.
        tool_map: Tool name → tool callable mapping.
        fallback_fn: The existing ``codemode_query_gen_node`` (or equivalent)
                     used when the plan is invalid or confidence is too low.
        state: Current LangGraph state, passed verbatim to *fallback_fn*.
        confidence_threshold: Plans below this score trigger the fallback.
        max_workers: Passed to WorkflowExecutor.

    Returns:
        ``{"step_results": dict, "used_fallback": bool}``
    """
    # 1. Confidence gate
    if plan.confidence < confidence_threshold:
        logger.info(
            "Plan confidence %.2f below threshold %.2f; using fallback LLM.",
            plan.confidence,
            confidence_threshold,
        )
        fallback_fn(state)
        return {"step_results": {}, "used_fallback": True}

    # 2. Structural validation
    validator = WorkflowValidator(tool_map)
    result = validator.validate(plan)
    if not result:
        logger.warning(
            "Plan validation failed (%d errors); using fallback LLM. Errors: %s",
            len(result.errors),
            result.errors,
        )
        fallback_fn(state)
        return {"step_results": {}, "used_fallback": True, "validation_errors": result.errors}

    # 3. Execute the validated plan
    executor = WorkflowExecutor(tool_map, max_workers=max_workers)
    try:
        step_results = executor.execute(plan)
        logger.info("Plan executed successfully (%d steps).", len(plan.steps))
        return {"step_results": step_results, "used_fallback": False}
    except RuntimeError as exc:
        logger.error("Plan execution failed: %s; using fallback LLM.", exc)
        fallback_fn(state)
        return {"step_results": {}, "used_fallback": True, "execution_error": str(exc)}
