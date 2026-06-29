from fastapi import Request

from graph_agent_litellm.services.chat_service import ChatService
from graph_agent_litellm.services.operations_service import OperationsService


def get_chat_service(request: Request) -> ChatService:
    return request.app.state.chat_service


def get_operations_service(request: Request) -> OperationsService:
    return request.app.state.operations_service

