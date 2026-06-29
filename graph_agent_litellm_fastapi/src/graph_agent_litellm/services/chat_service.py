from graph_agent_litellm.agent.agent import GraphAgent
from graph_agent_litellm.agent.policies import normalize_inbound_messages
from graph_agent_litellm.api_models.chat import ChatRequest, ChatResponse


class ChatService:
    def __init__(self, agent: GraphAgent) -> None:
        self._agent = agent

    async def chat(self, request: ChatRequest) -> ChatResponse:
        normalized = request.normalized_input()
        messages = normalize_inbound_messages(normalized.messages)
        thread_id = normalized.thread_id or normalized.user_id
        return await self._agent.run(messages=messages, thread_id=thread_id)

