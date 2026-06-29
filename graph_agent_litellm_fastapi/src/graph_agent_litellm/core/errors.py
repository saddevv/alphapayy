class AppError(Exception):
    status_code = 500
    code = "internal_error"

    def __init__(self, message: str, *, details: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class AuthenticationError(AppError):
    status_code = 401
    code = "authentication_error"


class AuthorizationError(AppError):
    status_code = 403
    code = "authorization_error"


class ToolExecutionError(AppError):
    status_code = 400
    code = "tool_execution_error"


class UpstreamServiceError(AppError):
    status_code = 502
    code = "upstream_service_error"

