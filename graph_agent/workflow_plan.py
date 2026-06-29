"""Workflow plan schema, validator, and dependency-reference resolver.

This module defines the structured plan format that the fine-tuned Qwen 1.5B
model will generate.  A plan is a DAG of tool steps; each step may reference
outputs of prior steps via ``$<step_id>.<field>`` tokens.

Usage flow (new architecture):
    1. Qwen 1.5B receives the user query and emits a WorkflowPlan JSON.
    2. WorkflowValidator.validate() checks that the plan is safe to execute.
    3. WorkflowExecutor (workflow_executor.py) runs the steps in dependency
       order, resolving ``$step_id.field`` references between steps.
    4. The large LLM (GPT-4o / Nemotron) synthesises the final answer from the
       aggregated tool results.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field, model_validator

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Compact tool schema (used at inference time to stay within Qwen's context)
# ---------------------------------------------------------------------------

#: Identifier fields that may be referenced across steps via $step_id.field
REFERENCEABLE_FIELDS = {
    "id",
    "userPrincipalName",
    "mail",
    "groupId",
    "appId",
    "deviceId",
    "managedDeviceId",
    "incidentId",
    "alertId",
    "caseId",
    "simulationId",
    "principalId",
}

#: Step-reference pattern: ``$s1.id``, ``$step2.userPrincipalName``, etc.
_REF_PATTERN = re.compile(r"^\$([a-zA-Z_]\w*)\.(\w+)$")


# ---------------------------------------------------------------------------
# Plan data model
# ---------------------------------------------------------------------------

class WorkflowStep(BaseModel):
    """A single tool call within an execution plan."""

    step_id: str = Field(
        description="Unique identifier for this step within the plan (e.g. 's1', 's2')."
    )
    tool: str = Field(
        description="Exact name of the tool to call (must exist in TOOL_MAP)."
    )
    args: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Tool arguments. Values may be literal scalars or step-reference strings "
            "of the form '$<step_id>.<field>' (e.g. '$s1.id')."
        ),
    )
    depends_on: list[str] = Field(
        default_factory=list,
        description="List of step_ids that must complete before this step runs.",
    )
    description: str = Field(
        default="",
        description="Optional human-readable rationale for this step.",
    )


class WorkflowPlan(BaseModel):
    """Ordered list of tool steps that together fulfil the user request."""

    steps: list[WorkflowStep] = Field(
        description="Ordered list of tool-call steps. Each step may depend on earlier steps."
    )
    final_action: str = Field(
        default="execute_plan",
        description="Downstream action after all steps complete ('execute_plan' or 'clarify').",
    )
    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description=(
            "Model's self-reported confidence (0–1). "
            "Values below the configured threshold trigger fallback to the large LLM."
        ),
    )

    @model_validator(mode="after")
    def _step_ids_unique(self) -> "WorkflowPlan":
        ids = [s.step_id for s in self.steps]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate step_ids detected in WorkflowPlan")
        return self


# ---------------------------------------------------------------------------
# Validation result
# ---------------------------------------------------------------------------

@dataclass
class ValidationResult:
    valid: bool
    errors: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return self.valid


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------

class WorkflowValidator:
    """Validate a WorkflowPlan before execution.

    Checks:
    - All referenced tool names exist in TOOL_MAP.
    - Dependency graph is a DAG (no cycles).
    - Step-reference tokens (``$s1.id``) point to steps that are listed in
      ``depends_on`` and the referenced field is referenceable.
    - ``final_action`` is a known value.
    """

    KNOWN_FINAL_ACTIONS = {"execute_plan", "clarify"}

    def __init__(self, tool_map: dict[str, Any]) -> None:
        self._tool_map = tool_map

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def validate(self, plan: WorkflowPlan) -> ValidationResult:
        errors: list[str] = []

        step_index = {s.step_id: s for s in plan.steps}

        for step in plan.steps:
            self._check_tool_exists(step, errors)
            self._check_depends_on_exist(step, step_index, errors)
            self._check_arg_references(step, step_index, errors)

        self._check_no_cycles(plan, step_index, errors)
        self._check_final_action(plan, errors)

        valid = len(errors) == 0
        if not valid:
            logger.warning("WorkflowPlan validation failed: %s", errors)
        return ValidationResult(valid=valid, errors=errors)

    # ------------------------------------------------------------------
    # Internal checks
    # ------------------------------------------------------------------

    def _check_tool_exists(self, step: WorkflowStep, errors: list[str]) -> None:
        if step.tool not in self._tool_map:
            errors.append(
                f"Step '{step.step_id}': unknown tool '{step.tool}'. "
                "Check TOOL_MAP for valid tool names."
            )

    def _check_depends_on_exist(
        self,
        step: WorkflowStep,
        step_index: dict[str, WorkflowStep],
        errors: list[str],
    ) -> None:
        for dep in step.depends_on:
            if dep not in step_index:
                errors.append(
                    f"Step '{step.step_id}' depends_on unknown step '{dep}'."
                )

    def _check_arg_references(
        self,
        step: WorkflowStep,
        step_index: dict[str, WorkflowStep],
        errors: list[str],
    ) -> None:
        for arg_name, value in step.args.items():
            if not isinstance(value, str):
                continue
            m = _REF_PATTERN.match(value)
            if m is None:
                continue
            ref_step_id, ref_field = m.group(1), m.group(2)
            if ref_step_id not in step_index:
                errors.append(
                    f"Step '{step.step_id}' arg '{arg_name}': "
                    f"references unknown step '{ref_step_id}'."
                )
            elif ref_step_id not in step.depends_on:
                errors.append(
                    f"Step '{step.step_id}' arg '{arg_name}' references "
                    f"'{ref_step_id}' but '{ref_step_id}' is not listed in depends_on."
                )
            if ref_field not in REFERENCEABLE_FIELDS:
                errors.append(
                    f"Step '{step.step_id}' arg '{arg_name}': "
                    f"field '{ref_field}' is not in REFERENCEABLE_FIELDS. "
                    f"Allowed: {sorted(REFERENCEABLE_FIELDS)}"
                )

    def _check_no_cycles(
        self,
        plan: WorkflowPlan,
        step_index: dict[str, WorkflowStep],
        errors: list[str],
    ) -> None:
        """Kahn's algorithm (topological sort) to detect cycles."""
        in_degree: dict[str, int] = {s.step_id: 0 for s in plan.steps}
        for step in plan.steps:
            for dep in step.depends_on:
                if dep in in_degree:
                    in_degree[step.step_id] += 1

        queue = [sid for sid, deg in in_degree.items() if deg == 0]
        visited = 0
        while queue:
            sid = queue.pop()
            visited += 1
            for step in plan.steps:
                if sid in step.depends_on:
                    in_degree[step.step_id] -= 1
                    if in_degree[step.step_id] == 0:
                        queue.append(step.step_id)

        if visited != len(plan.steps):
            errors.append("WorkflowPlan contains a dependency cycle.")

    def _check_final_action(self, plan: WorkflowPlan, errors: list[str]) -> None:
        if plan.final_action not in self.KNOWN_FINAL_ACTIONS:
            errors.append(
                f"Unknown final_action '{plan.final_action}'. "
                f"Must be one of {self.KNOWN_FINAL_ACTIONS}."
            )


# ---------------------------------------------------------------------------
# Dependency-reference resolver
# ---------------------------------------------------------------------------

def resolve_step_references(
    args: dict[str, Any],
    completed_results: dict[str, Any],
) -> dict[str, Any]:
    """Replace ``$step_id.field`` tokens in *args* with actual values.

    Args:
        args: Raw argument dict as emitted by the Qwen model.
        completed_results: Map of step_id → parsed tool result (dict or list).

    Returns:
        A new args dict with all reference tokens substituted.

    Raises:
        KeyError: If the referenced step has no result yet.
        ValueError: If the field cannot be found in the step result.
    """
    resolved: dict[str, Any] = {}
    for key, value in args.items():
        if isinstance(value, str):
            m = _REF_PATTERN.match(value)
            if m:
                ref_step_id, ref_field = m.group(1), m.group(2)
                step_result = completed_results[ref_step_id]
                resolved[key] = _extract_field(step_result, ref_field, ref_step_id)
                continue
        resolved[key] = value
    return resolved


def _extract_field(result: Any, field: str, step_id: str) -> Any:
    """Extract *field* from a tool result (dict, list, or OData envelope)."""
    if isinstance(result, dict):
        # OData envelope: {"value": [...]}
        if "value" in result and isinstance(result["value"], list):
            records = result["value"]
            if not records:
                raise ValueError(
                    f"Step '{step_id}' returned an empty list; "
                    f"cannot resolve field '{field}'."
                )
            first = records[0]
            if isinstance(first, dict) and field in first:
                return first[field]
        if field in result:
            return result[field]
    elif isinstance(result, list):
        if not result:
            raise ValueError(
                f"Step '{step_id}' returned an empty list; "
                f"cannot resolve field '{field}'."
            )
        first = result[0]
        if isinstance(first, dict) and field in first:
            return first[field]

    raise ValueError(
        f"Field '{field}' not found in result of step '{step_id}'. "
        f"Available keys: {list(result.keys()) if isinstance(result, dict) else type(result).__name__}"
    )
