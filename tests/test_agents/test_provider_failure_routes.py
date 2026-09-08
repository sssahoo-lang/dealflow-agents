"""What an agent endpoint does when the real model provider fails mid-request.

Uses fake_llm_failure (a model that raises instead of returning) rather than
a real ANTHROPIC_API_KEY -- the point under test is the route's own error
translation, not the SDK's, so a real network call would only make this
suite slower and flakier for no added coverage.
"""

import anthropic
import httpx

from app.agents.follow_up.graph import Draft


def _rate_limited() -> anthropic.RateLimitError:
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx.Response(
        429, request=request, json={"error": {"message": "rate limited"}}
    )
    return anthropic.RateLimitError(
        message="rate limited", response=response, body={"error": {}}
    )


def test_follow_up_returns_503_not_500_when_the_provider_fails(
    client, crm_data, token, fake_llm_failure
):
    fake_llm_failure(_rate_limited())

    resp = client.post(
        "/agents/follow-up",
        json={"deal_id": crm_data["deal"].id},
        headers=token("rep@test.com"),
    )

    assert resp.status_code == 503
    assert "again" in resp.json()["detail"].lower()


def test_query_returns_503_not_500_when_the_provider_fails(
    client, crm_data, token, fake_llm_failure
):
    fake_llm_failure(_rate_limited())

    resp = client.post(
        "/agents/query",
        json={"question": "which deals are worth the most?"},
        headers=token("rep@test.com"),
    )

    assert resp.status_code == 503


def test_ownership_is_still_enforced_before_the_agent_ever_runs(
    client, crm_data, token, fake_llm_failure
):
    # A provider failure must not become a way to probe deal ids you don't
    # own -- ownership has to fail first, distinctly from a 503.
    fake_llm_failure(_rate_limited())

    resp = client.post(
        "/agents/follow-up",
        json={"deal_id": crm_data["other_deal"].id},
        headers=token("rep@test.com"),
    )

    assert resp.status_code == 403


def test_a_successful_call_is_unaffected_by_the_failure_path_existing(
    client, crm_data, token, fake_llm
):
    # Regression guard: wrapping the call in error translation must not
    # change behavior on the happy path.
    fake_llm(Draft(subject="Next steps", body="Hi Dana, checking in."))

    resp = client.post(
        "/agents/follow-up",
        json={"deal_id": crm_data["deal"].id},
        headers=token("rep@test.com"),
    )

    assert resp.status_code == 200
    assert resp.json()["subject"] == "Next steps"
