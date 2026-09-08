"""One real call per agent against the actual Anthropic API.

Skipped by default -- and skipped in CI, since no key is configured there
on purpose (see the README's "no API key, no network calls" story). This is
the counterpart to that default: a way to prove the wiring genuinely works
end to end, not just that the stub path works, without ever making that
proof a requirement to run the rest of the suite.

Run explicitly, with a real key:

    ANTHROPIC_API_KEY=sk-ant-... .venv/bin/pytest tests/test_agents/test_live_anthropic.py -v

Assertions here check *shape*, not content: a real model's wording is not
deterministic, and pinning these tests to exact text would make them break
on every model upgrade for no real gain. What's worth proving is that the
graph runs end to end against the real SDK -- structured output actually
parses into the Pydantic schema, the tool-calling loop actually calls a
tool -- which is exactly the part a stub can't exercise.
"""

import os

import pytest

from app.agents.llm import get_chat_model
from app.config import settings
from app.models.enums import Priority

pytestmark = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="set ANTHROPIC_API_KEY to run live Anthropic tests",
)


@pytest.fixture(autouse=True)
def _force_anthropic_provider(monkeypatch):
    # A key can be present without LLM_PROVIDER=anthropic being set globally
    # (e.g. it's in .env but the default LLM_PROVIDER=stub line wasn't
    # changed) -- this test's whole point is to verify the anthropic path
    # specifically, regardless of what the rest of the app is configured to
    # run as day to day.
    monkeypatch.setattr(settings, "llm_provider", "anthropic")


def test_get_chat_model_returns_a_real_chat_anthropic():
    from langchain_anthropic import ChatAnthropic

    model = get_chat_model("lead_scoring")
    assert isinstance(model, ChatAnthropic)


def test_lead_scoring_runs_end_to_end_against_the_real_model(db, crm_data):
    from app.agents.lead_scoring.graph import run

    result = run(db, crm_data["deal"].id)

    assert 0 <= result["score"] <= 100
    Priority(result["priority"])  # raises ValueError if the model returned junk
    assert len(result["reasoning"]) > 0


def test_follow_up_drafting_runs_end_to_end_against_the_real_model(db, crm_data):
    from app.agents.follow_up.graph import run

    result = run(db, crm_data["deal"].id)

    assert len(result["subject"]) > 0
    assert len(result["body"]) > 0
    # The prompt caps this at 150 words; a generous ceiling here catches a
    # genuinely broken prompt without being brittle about the model's exact
    # word count on any given run.
    assert len(result["body"].split()) < 400


def test_nl_query_actually_calls_a_tool_rather_than_guessing(db, crm_data, users):
    from app.agents.nl_query.graph import run

    result = run(db, users["rep"], "Which of my deals are worth the most?")

    assert result["tool_calls"], "the model answered without calling any tool"
    assert len(result["answer"]) > 0
