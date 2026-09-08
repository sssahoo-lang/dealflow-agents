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


def describe_anthropic_error(exc: Exception) -> str:
    """Turns an SDK exception into a message worth showing a caller.

    The stub provider never fails, so nothing in this codebase had to think
    about a model call going wrong until now. A real provider can: a bad key,
    a rate limit, a network blip. Each needs a different message -- "check
    your key" and "try again in a moment" are not the same instruction --
    and none of them should leak an SDK stack trace to an API caller.

    Import is local to keep `anthropic` an optional-at-import-time dependency
    of this module: callers that never hit this path (the stub, most of the
    test suite) don't need the package importable to use everything else here.
    """
    import anthropic

    if isinstance(exc, anthropic.AuthenticationError):
        return "ANTHROPIC_API_KEY is missing or invalid."
    if isinstance(exc, anthropic.RateLimitError):
        return "The model provider is rate-limiting requests. Try again shortly."
    if isinstance(exc, anthropic.APIConnectionError):
        return "Could not reach the model provider. Check network connectivity."
    if isinstance(exc, anthropic.AnthropicError):
        return f"The model provider returned an error: {exc}"
    raise TypeError(f"Not an anthropic.AnthropicError: {type(exc).__name__}")
