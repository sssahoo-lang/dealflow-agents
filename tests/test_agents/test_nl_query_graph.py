"""Graph-level tests for the NL query agent.

test_nl_query_tools.py covers the tools; this file covers the state machine around
them -- the conditional edge, the router/tools loop, and the loop bound. Those are
the parts a tools-only test suite silently leaves unverified.
"""

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from app.agents.nl_query.graph import MAX_TOOL_ROUNDS, run


def tool_call(name: str, args: dict | None = None, call_id: str = "call-1") -> AIMessage:
    return AIMessage(
        content="", tool_calls=[{"name": name, "args": args or {}, "id": call_id}]
    )


class ScriptedModel:
    """Returns queued responses in order, repeating the last one once exhausted.

    Repeating matters: it lets a single always-calls-a-tool response drive the
    runaway-loop test without hand-rolling an infinite generator.
    """

    def __init__(self, *responses: AIMessage):
        self._responses = list(responses)
        self.seen: list[list] = []  # messages passed in on each call

    def bind_tools(self, tools):
        return self

    @property
    def invocations(self) -> int:
        return len(self.seen)

    def invoke(self, messages):
        self.seen.append(list(messages))
        if len(self._responses) > 1:
            return self._responses.pop(0)
        return self._responses[0]


@pytest.fixture
def scripted(monkeypatch):
    def _install(*responses: AIMessage) -> ScriptedModel:
        model = ScriptedModel(*responses)
        monkeypatch.setattr(
            "app.agents.nl_query.graph.get_chat_model", lambda name: model
        )
        return model

    return _install


def test_tool_call_is_executed_and_recorded(db, crm_data, users, scripted):
    scripted(
        tool_call("query_deals"),
        AIMessage(content="You have one deal in proposal."),
    )

    result = run(db, users["rep"], "what deals do I have?")

    assert result["tool_calls"] == ["query_deals"]
    assert result["answer"] == "You have one deal in proposal."


def test_tool_output_reaches_the_model(db, crm_data, users, scripted):
    """The tool result must be fed back, not just executed and dropped."""
    model = scripted(
        tool_call("query_deals"), AIMessage(content="summary")
    )

    run(db, users["rep"], "what deals do I have?")

    # The second router call must see a ToolMessage carrying the rep's own deal --
    # otherwise the tool ran but its output never informed the answer.
    assert model.invocations == 2
    second_call = model.seen[1]
    tool_messages = [m for m in second_call if isinstance(m, ToolMessage)]
    assert len(tool_messages) == 1
    assert "Acme rollout" in tool_messages[0].content
    assert "Other rep deal" not in tool_messages[0].content


def test_reply_without_tool_calls_skips_the_tools_node(db, crm_data, users, scripted):
    model = scripted(AIMessage(content="No lookup needed."))

    result = run(db, users["rep"], "hello")

    assert result["answer"] == "No lookup needed."
    assert result["tool_calls"] == []
    assert model.invocations == 1  # router ran once, tools never did


def test_runaway_tool_calling_is_bounded(db, crm_data, users, scripted):
    """A model that calls a tool every single turn must not spin forever."""
    model = scripted(tool_call("query_deals"))

    result = run(db, users["rep"], "keep going")

    assert len(result["tool_calls"]) <= MAX_TOOL_ROUNDS + 1
    assert model.invocations <= MAX_TOOL_ROUNDS + 2


def test_hitting_the_bound_explains_itself(db, crm_data, users, scripted):
    """Bailing out at the cap must not hand the caller a silent empty answer.

    The last message in that path is a tool call, whose content is "" -- returning
    it verbatim gave the user a 200 with an empty string and no explanation.
    """
    scripted(tool_call("query_deals"))

    result = run(db, users["rep"], "keep going")

    assert result["answer"], "bailing out at the round cap returned an empty answer"
    assert str(MAX_TOOL_ROUNDS) in result["answer"]


def test_unknown_tool_name_does_not_crash_the_graph(db, crm_data, users, scripted):
    """ToolNode reports the failure back to the model rather than raising."""
    scripted(tool_call("drop_all_tables"), AIMessage(content="I cannot do that."))

    result = run(db, users["rep"], "delete everything")

    assert result["answer"] == "I cannot do that."


# --- endpoint, running on the real default (stub) provider -------------------


def test_query_endpoint_is_scoped_to_the_caller(client, crm_data, token):
    """Same question, two roles: the agent must not leak another rep's deals."""
    rep = client.post(
        "/agents/query",
        json={"question": "list all deals"},
        headers=token("rep@test.com"),
    )
    admin = client.post(
        "/agents/query",
        json={"question": "list all deals"},
        headers=token("admin@test.com"),
    )

    assert rep.status_code == 200 and admin.status_code == 200
    assert "Acme rollout" in rep.json()["answer"]
    assert "Other rep deal" not in rep.json()["answer"]
    assert "Other rep deal" in admin.json()["answer"]


def test_query_endpoint_requires_auth(client):
    assert client.post("/agents/query", json={"question": "anything"}).status_code == 401
