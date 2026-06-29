# Fine-Tuned Workflow Planning vs In-Context Tool Call Reasoning

Comparison of two approaches for executing Microsoft Graph API operations from natural language.

---

## 1. How Each Approach Works

### Fine-Tuned Workflow Planning (Qwen 1.5B)

A small model (Qwen 1.5B) is fine-tuned on 3,000 synthetic examples to emit a structured `WorkflowPlan` JSON — a DAG of tool steps with arguments and inter-step references (`$s1.id`). The plan is validated (tool names, cycles, reference integrity) then executed deterministically by `WorkflowExecutor`. A large LLM (GPT-4o / Nemotron) only synthesizes the final human-readable answer from collected results.

```
User query → Qwen 1.5B → WorkflowPlan JSON → validate → execute tools → large LLM → answer
```

### In-Context Tool Call Reasoning (Codemode)

A large LLM (GPT-4o / Nemotron) receives the full tool catalog (109 tools with schemas), conversation history, and system prompts at every turn. It reasons about which tools to call, emits tool calls via LangChain's function-calling, and iterates up to `CODEMODE_MAX_TURNS` with an evaluator deciding whether to continue.

```
User query → router LLM → [schema lookup →] query LLM → tool calls → evaluator LLM → [loop or] → final LLM → answer
```

---

## 2. Token & Latency Comparison

| Metric | Fine-Tuned Planner | In-Context Codemode |
|--------|-------------------|-------------------|
| **Planning model size** | 1.5B parameters | 200B+ parameters (GPT-4o class) |
| **System prompt size** | ~8,900 chars (compact tool list, no schemas) | ~4,000+ chars per LLM call + full tool JSON schemas (~109 tools × ~200 tokens each ≈ 22K tokens of tool definitions) |
| **Input tokens per request** | ~2,500 tokens (system + user query) | ~25,000–35,000 tokens (system prompt + tool schemas + conversation history per turn) |
| **Output tokens per request** | ~60–120 tokens (structured JSON) | ~200–800 tokens per turn × 2–4 turns = ~400–3,200 tokens |
| **LLM calls per request** | 1 (planner) + 1 (final answer) = **2** | 1 (router) + 1 (query gen) + 1 (evaluator) + 1 (final) = **3–7** (with iteration) |
| **Inference latency** | ~100–300ms (Qwen 1.5B local/NIM) + tool execution + final LLM | ~2–5s per LLM call × 3–7 calls = **6–35s** |
| **Cost per request** | Minimal (self-hosted 1.5B) + 1 large LLM call | 3–7 large LLM calls at ~$0.005–0.015/call each |

---

## 3. Accuracy Characteristics

### Fine-Tuned Planner

**Strengths:**
- Deterministic tool selection — no hallucinated tool names or arguments after validation
- Step references (`$s1.id`) are resolved mechanically, eliminating argument-passing errors
- Confidence gating (`< 0.6`) triggers automatic fallback to the large LLM path
- Validated before execution: cycle detection, tool existence, reference integrity
- Consistent behavior — same query always produces same plan

**Weaknesses:**
- Limited to patterns seen in training data (3,000 examples across 69 operations)
- Cannot handle novel operation combinations or unusual argument patterns without retraining
- No reasoning about ambiguous queries — either plans confidently or falls back
- Dataset is synthetic (not from real user traces), so edge cases may be underrepresented
- Hard distribution: 76% easy, 20% medium, 4% hard — may underperform on complex multi-step queries

### In-Context Codemode

**Strengths:**
- Can reason about novel, complex, and ambiguous queries
- Access to full tool schemas enables correct argument construction for any operation
- Evaluator loop can self-correct (retry with different tools/params)
- User identifier resolution (`_resolve_user_identifier`) handles display-name → GUID lookups inline
- Context compaction keeps conversation manageable across turns

**Weaknesses:**
- Tool selection degrades with catalog size — 109 tools push context limits
- LLM may hallucinate tool names, invent arguments, or select wrong tools
- Multi-turn iteration adds latency and cost even for simple queries
- Missing tool call guard needed (synthetic injection when LLM fails to call tools)
- Non-deterministic — same query may produce different tool sequences

---

## 4. Context Size Impact

| Factor | Fine-Tuned | In-Context |
|--------|-----------|-----------|
| **Tool catalog representation** | Flat name list (~8.9K chars) | Full JSON schemas with descriptions (~22K tokens) |
| **Conversation history** | Not passed to planner | Last 8 messages (compacted) per LLM call |
| **Tool result handling** | Raw JSON stored, only sent to final LLM | Compacted to 1,400 chars per tool result (record count + key identifiers) |
| **Scaling with tool count** | Linear growth in system prompt (name-only) | Quadratic pressure (schema tokens × turns) |
| **Multi-step overhead** | Single plan emission regardless of step count | Each iteration re-sends full context |

The fine-tuned approach uses roughly **10–15x fewer input tokens** per request because it replaces verbose tool schemas with a compact name list and eliminates iterative re-prompting.

---

## 5. When to Use Each

| Scenario | Recommended Approach |
|----------|---------------------|
| Simple CRUD (get user, list groups, create user) | Fine-tuned planner — fast, cheap, accurate |
| Multi-step with known patterns (disable user + remove from group) | Fine-tuned planner — trained on these patterns |
| Novel/complex queries not in training data | In-context codemode — can reason from schemas |
| Ambiguous queries needing clarification | In-context codemode — can ask follow-up questions |
| High-throughput / batch operations | Fine-tuned planner — 10x lower latency and cost |
| Edge cases with unusual OData filters | In-context codemode — has full schema context |

---

## 6. Dataset Statistics

| Metric | Value |
|--------|-------|
| Total training records | 3,000 (full) / 300 (sample) |
| Format | Chat-completion JSONL (system/user/assistant) |
| Difficulty distribution | 76% easy, 20% medium, 4% hard |
| Multi-step ratio | 21% multi-step, 79% single-step |
| Categories | user_management (27%), security_operations (32%), device_management (12%), application_management (11%), group_management (8%), audit/generic/clarification (10%) |
| Avg assistant output | ~259 chars (compact JSON plans) |
| Step count range | 0–6 steps per plan |

---

## 7. Hybrid Architecture (Current Design)

The codebase implements a **confidence-gated hybrid** via `execute_plan_with_fallback()`:

1. Qwen 1.5B emits a `WorkflowPlan` with a confidence score
2. If confidence < 0.6 → fall back to in-context codemode
3. If validation fails (bad tool names, cycles, broken refs) → fall back
4. If execution fails at runtime → fall back
5. Only the final answer synthesis uses the large LLM in the happy path

This gives the cost/speed benefits of fine-tuning for common queries (~80% of traffic) while preserving full reasoning capability for the long tail.
