# Synthetic Router Dataset

This project includes a synthetic dataset generator for router-model fine-tuning:

- Script: `/Users/apple/Desktop/graph_agent_standalone/scripts/generate_synthetic_router_dataset.py`

## What it generates

JSONL records in the format:

```json
{
  "input": {
    "query": "disable alex.woods@contoso.com and remove access from group a3f7d7f5-3f11-4a9a-b57b-7a57b7d2d001",
    "history": []
  },
  "output": {
    "plan": [
      {
        "step_id": "s1",
        "tool": "search_user_by_upn_tool",
        "args": {"upn": "alex.woods@contoso.com"},
        "depends_on": []
      },
      {
        "step_id": "s2",
        "tool": "set_user_account_enabled_tool",
        "args": {"user_id": "$s1.id", "account_enabled": false},
        "depends_on": ["s1"]
      }
    ],
    "final_action": "execute_plan"
  },
  "meta": {
    "source": "synthetic_multi_step",
    "difficulty": "medium",
    "split": "train",
    "generated_at": "2026-02-27T00:00:00+00:00"
  }
}
```

## Usage

Run from repo root:

```bash
./venv/bin/python scripts/generate_synthetic_router_dataset.py \
  --output data/synthetic_graph_router_dataset.jsonl \
  --rows 1000 \
  --seed 42
```

## Arguments

- `--output`: output JSONL path (default: `data/synthetic_graph_router_dataset.jsonl`)
- `--rows`: total number of rows to generate
- `--seed`: RNG seed for reproducibility

## Notes

- The script deduplicates resource aliases in `OPERATIONS_REGISTRY`.
- Single-step records always use `graph_operation_tool` with explicit structured arguments.
- Multi-step records use specific tool calls plus `depends_on` references.
- Use this as bootstrap data; mix with real traces and human-reviewed labels before final training.
