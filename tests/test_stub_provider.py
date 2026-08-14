"""Tests for the no-API-key stub provider and for provider selection.

The stub is what makes this repo runnable by anyone who clones it, so its
behaviour is load-bearing even though it isn't a model. These tests pin the
parts other code depends on: the score bands, determinism, schema dispatch,
and the two-phase tool-call contract that terminates the NL query loop.
"""

import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from pydantic import BaseModel

from app.agents.follow_up.graph import Draft
from app.agents.lead_scoring.graph import LeadScore
from app.agents.llm import get_chat_model
from app.agents.nl_query.tools import build_tools
from app.agents.stub import StubChatModel


def context(
    value: float = 50000,
    title: str | None = "VP of Operations",
    stage: str = "proposal",
    activities: int = 2,
    industry: str | None = "Manufacturing",
) -> list:
    payload = {
        "deal": {"id": 1, "name": "Test deal", "stage": stage, "value": value},
        "company": {"name": "Acme", "industry": industry},
        "contact": {"name": "Dana Reyes", "title": title},
        "activity_history": [
            {"type": "call", "subject": f"Touch {i}", "body": "", "created_at": ""}
            for i in range(activities)
        ],
    }
    return [("system", "irrelevant"), ("human", json.dumps(payload))]


def score(**kwargs) -> LeadScore:
    model = StubChatModel("lead_scoring").with_structured_output(LeadScore)
    return model.invoke(context(**kwargs))


# --- lead scoring heuristic --------------------------------------------------


def test_strong_deal_scores_high():
    result = score(value=200000, title="Chief Operating Officer", activities=4)

    assert result.score >= 80
    assert result.priority.value == "high"


def test_weak_deal_scores_low():
    result = score(value=2000, title=None, stage="new", activities=0, industry=None)

    assert result.score < 50
    assert result.priority.value == "low"


def test_score_is_clamped_to_the_valid_range():
    """Every component maxed out must still satisfy the 0-100 schema bound."""
    result = score(value=10_000_000, title="CEO", stage="won", activities=50)

    assert 0 <= result.score <= 100


def test_seniority_moves_the_score():
    senior = score(title="VP of Sales").score
    junior = score(title="Procurement Analyst").score
    absent = score(title=None).score

    assert senior > junior > absent


def test_scoring_is_deterministic():
    assert score().score == score().score
    assert score().reasoning == score().reasoning


def test_reasoning_discloses_that_it_is_not_a_model():
    """A reader must never mistake stub output for model output."""
    assert "stub" in score().reasoning.lower()


# --- schema dispatch ---------------------------------------------------------


def test_draft_schema_produces_a_subject_and_body():
    model = StubChatModel("follow_up").with_structured_output(Draft)

    result = model.invoke(context())

    assert result.subject
    assert "Dana" in result.body
    assert "stub" in result.body.lower()


def test_unknown_schema_fails_loudly():
    class Unsupported(BaseModel):
        foo: str

    model = StubChatModel("x").with_structured_output(Unsupported)

    with pytest.raises(NotImplementedError) as excinfo:
        model.invoke(context())

    assert "Unsupported" in str(excinfo.value)
    assert "anthropic" in str(excinfo.value)  # points at the way out


def test_malformed_context_does_not_crash():
    """Real prompts are JSON, but a non-JSON human turn must not explode."""
    model = StubChatModel("lead_scoring").with_structured_output(LeadScore)

    result = model.invoke([("human", "not json at all")])

    assert 0 <= result.score <= 100


# --- tool routing ------------------------------------------------------------


@pytest.fixture
def caller(db, crm_data, users):
    return StubChatModel("nl_query").bind_tools(build_tools(db, users["rep"]))


def routed_tool(caller, question: str) -> str:
    response = caller.invoke([HumanMessage(question)])
    return response.tool_calls[0]["name"]


def test_aggregate_questions_route_to_aggregate_stats(caller):
    assert routed_tool(caller, "how many deals by stage?") == "aggregate_stats"
    assert routed_tool(caller, "what is the total pipeline?") == "aggregate_stats"


def test_priority_grouping_is_detected(caller):
    response = caller.invoke([HumanMessage("give me the breakdown by priority")])

    assert response.tool_calls[0]["args"]["group_by"] == "priority"


def test_contact_questions_route_to_query_contacts(caller):
    assert routed_tool(caller, "who is the contact at Acme?") == "query_contacts"


def test_everything_else_routes_to_query_deals(caller):
    assert routed_tool(caller, "show me what's open") == "query_deals"


def test_stage_keyword_becomes_a_filter(caller):
    response = caller.invoke([HumanMessage("show me deals in negotiation")])

    assert response.tool_calls[0]["args"].get("stage") == "negotiation"


# --- the two-phase contract that terminates the loop -------------------------


def test_first_call_requests_a_tool(caller):
    response = caller.invoke([HumanMessage("list deals")])

    assert response.tool_calls
    assert response.content == ""


def test_call_after_tool_results_summarises_and_stops(caller):
    """Returning further tool calls here would loop forever."""
    rows = json.dumps([{"id": 1, "name": "Acme rollout", "stage": "proposal"}])

    response = caller.invoke(
        [
            HumanMessage("list deals"),
            AIMessage(content="", tool_calls=[{"name": "query_deals", "args": {}, "id": "c"}]),
            ToolMessage(content=rows, tool_call_id="c"),
        ]
    )

    assert not response.tool_calls
    assert "Acme rollout" in response.content


def test_empty_tool_results_are_reported_not_invented(caller):
    response = caller.invoke(
        [HumanMessage("list deals"), ToolMessage(content="[]", tool_call_id="c")]
    )

    assert not response.tool_calls
    assert "no matching records" in response.content.lower()


# --- provider selection ------------------------------------------------------


def test_default_provider_is_the_stub(monkeypatch):
    monkeypatch.setattr("app.agents.llm.settings.llm_provider", "stub")

    assert isinstance(get_chat_model("lead_scoring"), StubChatModel)


def test_unknown_provider_names_the_bad_value(monkeypatch):
    monkeypatch.setattr("app.agents.llm.settings.llm_provider", "gpt-9")

    with pytest.raises(ValueError, match="gpt-9"):
        get_chat_model("lead_scoring")


def test_anthropic_without_a_key_fails_with_a_useful_message(monkeypatch):
    """Better to fail here than with an opaque 401 mid-agent-run."""
    monkeypatch.setattr("app.agents.llm.settings.llm_provider", "anthropic")
    monkeypatch.setattr("app.agents.llm.settings.anthropic_api_key", "")

    with pytest.raises(RuntimeError) as excinfo:
        get_chat_model("lead_scoring")

    assert "ANTHROPIC_API_KEY" in str(excinfo.value)
    assert "stub" in str(excinfo.value)
