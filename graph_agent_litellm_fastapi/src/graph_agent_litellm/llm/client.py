import json
from typing import Any

from graph_agent_litellm.core.config import Settings
from graph_agent_litellm.llm.types import LLMResponse, LLMToolCall


class LiteLLMClient:
    """Small async adapter around LiteLLM.

    This is the only place in the application that should know LiteLLM response shapes.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def complete(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = "auto",
    ) -> LLMResponse:
        try:
            import litellm
        except ImportError as exc:
            raise RuntimeError(
                "LiteLLM is not installed. Install project dependencies with "
                "`pip install -e .` or `pip install litellm`."
            ) from exc

        kwargs: dict[str, Any] = {
            "model": self._settings.llm_model,
            "messages": messages,
            "temperature": self._settings.litellm_temperature,
            "max_tokens": self._settings.litellm_max_tokens,
            "timeout": self._settings.litellm_timeout_seconds,
        }
        if self._settings.litellm_api_base:
            kwargs["api_base"] = self._settings.litellm_api_base
        if self._settings.llm_api_key_provider:
            kwargs["api_key"] = self._settings.llm_api_key_provider
        if tools is not None:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = tool_choice

        raw = await litellm.acompletion(**kwargs)
        return self._normalize_response(raw)

    def _normalize_response(self, raw: Any) -> LLMResponse:
        choice = self._first_choice(raw)
        message = self._get(choice, "message", {}) or {}
        content = self._get(message, "content", "") or ""
        raw_tool_calls = self._get(message, "tool_calls", []) or []
        tool_calls = [self._normalize_tool_call(item, index) for index, item in enumerate(raw_tool_calls)]
        return LLMResponse(content=str(content), tool_calls=tool_calls, raw=raw)

    def _normalize_tool_call(self, raw: Any, index: int) -> LLMToolCall:
        call_id = self._get(raw, "id", None) or f"tool_call_{index + 1}"
        function = self._get(raw, "function", {}) or {}
        name = self._get(function, "name", "") or self._get(raw, "name", "")
        args_raw = self._get(function, "arguments", {}) or self._get(raw, "arguments", {})
        args = self._parse_args(args_raw)
        return LLMToolCall(id=str(call_id), name=str(name), args=args)

    @staticmethod
    def _parse_args(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                return parsed if isinstance(parsed, dict) else {}
            except json.JSONDecodeError:
                return {}
        return {}

    @staticmethod
    def _first_choice(raw: Any) -> Any:
        choices = LiteLLMClient._get(raw, "choices", []) or []
        return choices[0] if choices else {}

    @staticmethod
    def _get(obj: Any, key: str, default: Any = None) -> Any:
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key, default)
