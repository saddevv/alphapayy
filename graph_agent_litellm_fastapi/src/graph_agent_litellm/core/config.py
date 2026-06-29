import os
from functools import lru_cache

from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator


class Settings(BaseModel):
    app_name: str = "Microsoft Graph Agent LiteLLM"
    app_env: str = "local"
    api_key_name: str = "x-api-key"
    llm_api_key: str | None = None

    llm_model: str = "openai/gpt-4o-mini"
    llm_api_key_provider: str | None = None
    litellm_api_base: str | None = None
    litellm_temperature: float = 0
    litellm_max_tokens: int = 2048
    litellm_timeout_seconds: float = 60

    graph_tenant_id: str = ""
    graph_client_id: str = ""
    graph_client_secret: str = ""
    graph_scopes: list[str] = Field(default_factory=lambda: ["https://graph.microsoft.com/.default"])
    graph_default_api_version: str = "v1.0"
    graph_timeout_seconds: float = 30

    agent_max_turns: int = 4
    agent_max_tool_calls: int = 8
    agent_parallel_reads: bool = True
    agent_require_mutation_confirmation: bool = True

    @field_validator("graph_scopes", mode="before")
    @classmethod
    def split_graph_scopes(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return value

    @field_validator("agent_max_turns")
    @classmethod
    def clamp_max_turns(cls, value: int) -> int:
        return max(1, min(value, 10))

    @field_validator("agent_max_tool_calls")
    @classmethod
    def clamp_max_tool_calls(cls, value: int) -> int:
        return max(1, min(value, 20))

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv(override=False)
        return cls(
            app_name=_get_str("APP_NAME", cls.model_fields["app_name"].default),
            app_env=_get_str("APP_ENV", cls.model_fields["app_env"].default),
            api_key_name=_get_str("API_KEY_NAME", cls.model_fields["api_key_name"].default),
            llm_api_key=_get_optional_str("LLM_API_KEY"),
            llm_model=_get_str("LLM_MODEL", cls.model_fields["llm_model"].default),
            llm_api_key_provider=_get_optional_str("LLM_API_KEY_PROVIDER"),
            litellm_api_base=_get_optional_str("LITELLM_API_BASE"),
            litellm_temperature=_get_float("LITELLM_TEMPERATURE", 0),
            litellm_max_tokens=_get_int("LITELLM_MAX_TOKENS", 2048),
            litellm_timeout_seconds=_get_float("LITELLM_TIMEOUT_SECONDS", 60),
            graph_tenant_id=_get_str("GRAPH_TENANT_ID", ""),
            graph_client_id=_get_str("GRAPH_CLIENT_ID", ""),
            graph_client_secret=_get_str("GRAPH_CLIENT_SECRET", ""),
            graph_scopes=_get_str("GRAPH_SCOPES", "https://graph.microsoft.com/.default"),
            graph_default_api_version=_get_str("GRAPH_DEFAULT_API_VERSION", "v1.0"),
            graph_timeout_seconds=_get_float("GRAPH_TIMEOUT_SECONDS", 30),
            agent_max_turns=_get_int("AGENT_MAX_TURNS", 4),
            agent_max_tool_calls=_get_int("AGENT_MAX_TOOL_CALLS", 8),
            agent_parallel_reads=_get_bool("AGENT_PARALLEL_READS", True),
            agent_require_mutation_confirmation=_get_bool(
                "AGENT_REQUIRE_MUTATION_CONFIRMATION",
                True,
            ),
        )


@lru_cache
def get_settings() -> Settings:
    return Settings.from_env()


def _get_str(name: str, default: str) -> str:
    value = os.getenv(name)
    return value if value is not None else default


def _get_optional_str(name: str) -> str | None:
    value = os.getenv(name)
    return value or None


def _get_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _get_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _get_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}
