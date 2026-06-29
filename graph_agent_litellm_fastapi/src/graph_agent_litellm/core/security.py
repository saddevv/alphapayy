from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader

from graph_agent_litellm.core.config import Settings


def build_api_key_dependency(settings: Settings):
    header = APIKeyHeader(name=settings.api_key_name, auto_error=False)

    def verify_api_key(api_key: str | None = Security(header)) -> bool:
        if not settings.llm_api_key:
            return True
        if not api_key:
            raise HTTPException(status_code=401, detail="API key is missing")
        if api_key != settings.llm_api_key:
            raise HTTPException(status_code=403, detail="Invalid API key")
        return True

    return verify_api_key

