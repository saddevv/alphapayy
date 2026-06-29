from typing import Any


def normalize_inbound_messages(messages: list[Any]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for message in messages:
        payload = message.model_dump(exclude_none=True) if hasattr(message, "model_dump") else dict(message)
        role = str(payload.get("role") or payload.get("type") or "user").lower()
        if role == "human":
            role = "user"
        if role == "ai":
            role = "assistant"
        if role not in {"system", "user", "assistant", "tool"}:
            role = "user"
        item: dict[str, Any] = {"role": role, "content": str(payload.get("content") or "")}
        if role == "assistant" and payload.get("tool_calls"):
            item["tool_calls"] = payload["tool_calls"]
        if role == "tool":
            item["tool_call_id"] = payload.get("tool_call_id")
            item["name"] = payload.get("name")
        normalized.append(item)
    return normalized

