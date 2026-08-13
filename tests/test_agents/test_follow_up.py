from app.agents.follow_up.graph import Draft, run
from app.models.activity import Activity


def test_draft_is_saved_as_draft_not_sent(db, crm_data, fake_llm):
    fake_llm(Draft(subject="Following up on the rollout", body="Hi Dana, ..."))

    result = run(db, crm_data["deal"].id)

    activity = db.get(Activity, result["activity_id"])
    assert activity.is_draft is True
    assert activity.subject == "Following up on the rollout"
    assert activity.meta["agent"] == "follow_up"
    # Agent-authored, so no human creator.
    assert activity.created_by_user_id is None


def test_follow_up_endpoint_requires_deal_ownership(client, crm_data, token, fake_llm):
    fake_llm(Draft(subject="s", body="b"))

    resp = client.post(
        "/agents/follow-up",
        json={"deal_id": crm_data["other_deal"].id},
        headers=token("rep@test.com"),
    )

    assert resp.status_code == 403


def test_follow_up_endpoint_returns_draft(client, crm_data, token, fake_llm):
    fake_llm(Draft(subject="Next steps", body="Hi Dana, checking in on the proposal."))

    resp = client.post(
        "/agents/follow-up",
        json={"deal_id": crm_data["deal"].id},
        headers=token("rep@test.com"),
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["subject"] == "Next steps"
    assert body["is_draft"] is True


def test_drafts_are_filterable(client, crm_data, token, fake_llm):
    fake_llm(Draft(subject="Next steps", body="..."))
    headers = token("rep@test.com")
    client.post("/agents/follow-up", json={"deal_id": crm_data["deal"].id}, headers=headers)

    resp = client.get("/activities?is_draft=true", headers=headers)

    assert resp.status_code == 200
    assert len(resp.json()) == 1
