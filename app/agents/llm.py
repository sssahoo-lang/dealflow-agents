from typing import Any

from app.config import settings

_MODELS = {
    "lead_scoring": settings.lead_scoring_model,
    "follow_up": settings.follow_up_model,
    "nl_query": settings.nl_query_model,
}


def get_chat_model(agent_name: str) -> Any:
    """Single construction point for every model call in the app.

    Tests monkeypatch this one function; never patch inside node modules.

    Provider is chosen by LLM_PROVIDER:
      stub      - deterministic, no key, no network (default; see app/agents/stub.py)
      anthropic - real Claude calls, requires ANTHROPIC_API_KEY
    """
    provider = settings.llm_provider.lower()

    if provider == "stub":
        from app.agents.stub import StubChatModel

        return StubChatModel(agent_name)

    if provider == "anthropic":
        if not settings.anthropic_api_key:
            raise RuntimeError(
                "LLM_PROVIDER=anthropic but ANTHROPIC_API_KEY is unset. "
                "Set the key in .env, or use LLM_PROVIDER=stub to run without one."
            )
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            model=_MODELS[agent_name],
            api_key=settings.anthropic_api_key,
            max_tokens=2048,
        )

    raise ValueError(
        f"Unknown LLM_PROVIDER {settings.llm_provider!r}. Expected 'stub' or 'anthropic'."
    )
