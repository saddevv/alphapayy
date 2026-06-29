from graph_agent_litellm.agent.policies import normalize_inbound_messages


def test_normalizes_langchain_style_roles() -> None:
    messages = normalize_inbound_messages(
        [
            {"role": "human", "content": "hi"},
            {"role": "ai", "content": "hello"},
            {"role": "unknown", "content": "fallback"},
        ]
    )

    assert [message["role"] for message in messages] == ["user", "assistant", "user"]

