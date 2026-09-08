"""describe_anthropic_error() turns an SDK exception into a message worth
showing a caller. Pure function, no network -- the stub provider never
raises any of this, so these are the first tests in the repo that exercise
what happens when a real model call goes wrong.
"""

import anthropic
import httpx
import pytest

from app.agents.llm import describe_anthropic_error


def _status_error(cls, status_code: int, body: dict) -> anthropic.APIStatusError:
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx.Response(status_code, request=request, json=body)
    return cls(message=str(body), response=response, body=body)


def test_authentication_error_names_the_actual_problem():
    exc = _status_error(
        anthropic.AuthenticationError, 401, {"error": {"message": "invalid x-api-key"}}
    )
    assert "ANTHROPIC_API_KEY" in describe_anthropic_error(exc)


def test_rate_limit_error_suggests_retrying():
    exc = _status_error(
        anthropic.RateLimitError, 429, {"error": {"message": "rate limited"}}
    )
    assert "again" in describe_anthropic_error(exc).lower()


def test_connection_error_names_the_network_not_the_key():
    exc = anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com"))
    message = describe_anthropic_error(exc)
    assert "network" in message.lower() or "reach" in message.lower()
    assert "API_KEY" not in message  # wrong diagnosis would send someone chasing the wrong fix


def test_an_unrecognised_anthropic_error_still_gets_a_message_not_a_crash():
    exc = _status_error(
        anthropic.InternalServerError, 500, {"error": {"message": "overloaded"}}
    )
    message = describe_anthropic_error(exc)
    assert message  # didn't raise, and isn't empty


def test_refuses_to_describe_something_that_is_not_an_anthropic_error():
    # A guard against this being called on the wrong exception by mistake --
    # a caller catching `anthropic.AnthropicError` and passing something
    # else in has a bug worth surfacing loudly, not a message worth hiding it.
    with pytest.raises(TypeError):
        describe_anthropic_error(ValueError("not an SDK error"))
