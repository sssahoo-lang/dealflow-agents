from langchain_anthropic import ChatAnthropic

from app.config import settings

_MODELS = {
    "lead_scoring": settings.lead_scoring_model,
    "follow_up": settings.follow_up_model,
    "nl_query": settings.nl_query_model,
}


def get_chat_model(agent_name: str) -> ChatAnthropic:
    """Single construction point for every Claude call in the app.

    Tests monkeypatch this one function; never patch inside node modules.
    """
    return ChatAnthropic(
        model=_MODELS[agent_name],
        api_key=settings.anthropic_api_key,
        max_tokens=2048,
    )
