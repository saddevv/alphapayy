import os
from typing import Optional, Dict, Any
import httpx
from dotenv import load_dotenv, find_dotenv

# Public interface type
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_nvidia_ai_endpoints import ChatNVIDIA

# Load .env defensively for entrypoints that do not call load_dotenv themselves.
load_dotenv(find_dotenv(usecwd=True), override=False)


def _init_azure_openai(**kwargs: Any) -> BaseChatModel:
    """Initialize Azure OpenAI chat model using env vars.

    Expected env vars:
    - OPENAI_DEPLOYMENT_NAME: Azure deployment name (required)
    Optional (handled by langchain-openai via env):
    - AZURE_OPENAI_API_KEY
    - AZURE_OPENAI_ENDPOINT
    - AZURE_OPENAI_API_VERSION
    """
    from langchain_openai.chat_models import AzureChatOpenAI

    deployment_name = os.getenv("OPENAI_DEPLOYMENT_NAME")
    if not deployment_name:
        raise RuntimeError(
            "OPENAI_DEPLOYMENT_NAME is required for Azure OpenAI provider"
        )

    temperature = _coerce_float(os.getenv("LLM_TEMPERATURE"))

    return AzureChatOpenAI(
        deployment_name=deployment_name,
        temperature=temperature if temperature is not None else 0,
        **kwargs,
    )


def _init_nvidia_llama(**kwargs: Any) -> BaseChatModel:
    """Initialize Nvidia Llama (Nemotron) via NIM endpoints.

    Supported env vars:
    - NVIDIA_BASE_URL: Base URL for the NIM endpoint (e.g., http://localhost:8000)
    - NVIDIA_MODEL: Model name (e.g., nvidia/Llama-3.1-Nemotron-Nano-4B-v1.1)
    - NVIDIA_API_KEY: Optional API key if your endpoint requires it
    """

    base_url = os.getenv("NVIDIA_BASE_URL", os.getenv("NIM_BASE_URL", "http://localhost:8000"))
    model = os.getenv(
        "NVIDIA_MODEL",
        os.getenv("NIM_MODEL", "nvidia/Llama-3.1-Nemotron-Nano-4B-v1.1"),
    )

    temperature = _coerce_float(os.getenv("LLM_TEMPERATURE"))

    # "api_key" is optional and only used if the endpoint requires it
    api_key = os.getenv("NVIDIA_API_KEY")

    init_kwargs: Dict[str, Any] = {
        "base_url": base_url,
        "model": model,
    }
    if temperature is not None:
        init_kwargs["temperature"] = temperature
    if api_key:
        init_kwargs["api_key"] = api_key

    init_kwargs.update(kwargs)

    return ChatNVIDIA(**init_kwargs)


def _normalize_openai_compatible_base_url(endpoint: str) -> str:
    """Convert endpoint variants into a base URL ChatOpenAI can use."""
    clean = endpoint.strip().rstrip("/")
    for suffix in ("/chat/completions", "/completions"):
        if clean.endswith(suffix):
            clean = clean[: -len(suffix)]
            break
    if not clean.endswith("/v1"):
        clean = f"{clean}/v1"
    return clean


def _discover_openai_compatible_model(base_url: str, api_key: str) -> Optional[str]:
    """Best-effort discovery of first available model from /models."""
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.get(f"{base_url.rstrip('/')}/models", headers=headers)
            response.raise_for_status()
            payload = response.json()
    except Exception:
        return None

    models = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(models, list):
        return None

    for item in models:
        if isinstance(item, dict):
            model_id = item.get("id")
            if isinstance(model_id, str) and model_id.strip():
                return model_id.strip()
    return None


def _init_openai_compatible(**kwargs: Any) -> BaseChatModel:
    """Initialize an OpenAI-compatible chat model."""
    from langchain_openai.chat_models import ChatOpenAI

    raw_endpoint = os.getenv(
        "OPENAI_COMPAT_ENDPOINT",
        "http://34.136.28.121:8000/v1/chat/completions",
    )
    base_url = _normalize_openai_compatible_base_url(raw_endpoint)
    api_key = os.getenv("OPENAI_COMPAT_API_KEY", os.getenv("OPENAI_API_KEY", ""))

    if not api_key:
        raise RuntimeError(
            "OPENAI_COMPAT_API_KEY (or OPENAI_API_KEY) is required for openai_compatible provider"
        )

    fallback_model = os.getenv("OPENAI_COMPAT_FALLBACK_MODEL", "openai-compatible-model").strip()
    model = os.getenv("OPENAI_COMPAT_MODEL", fallback_model).strip()
    if not model:
        model = fallback_model
    if model.lower() == "auto":
        discovered = _discover_openai_compatible_model(base_url, api_key)
        if discovered:
            model = discovered
        else:
            model = fallback_model

    temperature = _coerce_float(os.getenv("LLM_TEMPERATURE"))
    max_tokens = _coerce_int(os.getenv("LLM_MAX_TOKENS"))

    init_kwargs: Dict[str, Any] = {
        "model": model,
        "base_url": base_url,
        "api_key": api_key,
    }
    if temperature is not None:
        init_kwargs["temperature"] = temperature
    if max_tokens is not None:
        init_kwargs["max_tokens"] = max_tokens

    init_kwargs.update(kwargs)

    return ChatOpenAI(**init_kwargs)


def _coerce_float(value: Optional[str]) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None


def _coerce_int(value: Optional[str]) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except Exception:
        return None


def get_chat_model(**kwargs: Any) -> BaseChatModel:
    """Factory returning a LangChain BaseChatModel based on LLM_PROVIDER.

    Providers:
    - azure_openai (default)
    - nvidia_llama
    - openai_compatible

    Usage in existing code:
        from utils.llm_adapter import get_chat_model
        llm = get_chat_model(temperature=0)
    """
    provider = os.getenv("LLM_PROVIDER", "azure_openai").strip().lower()

    if provider == "azure_openai":
        return _init_azure_openai(**kwargs)
    elif provider == "nvidia_llama":
        return _init_nvidia_llama(**kwargs)
    elif provider in {"openai_compatible", "openai_compat", "self_hosted_openai"}:
        return _init_openai_compatible(**kwargs)

    else:
        # Default to Azure to remain backward compatible
        return _init_azure_openai(**kwargs)
