from app.agents.lead_scoring.graph import LeadScore, run
from app.models.activity import Activity
from app.models.deal import Deal
from app.models.enums import ActivityType, Priority


def test_scoring_persists_score_and_reasoning(db, crm_data, fake_llm):
    fake_llm(
        LeadScore(score=72.0, priority=Priority.medium, reasoning="Solid mid-market fit.")
    )
    deal_id = crm_data["deal"].id

    run(db, deal_id)

    deal = db.get(Deal, deal_id)
    assert deal.score == 72.0
    assert deal.priority is Priority.medium

    activity = (
        db.query(Activity)
        .filter(Activity.deal_id == deal_id, Activity.type == ActivityType.agent_generated)
        .one()
    )
    assert activity.body == "Solid mid-market fit."
    assert activity.meta["agent"] == "lead_scoring"
    assert activity.meta["flagged_high_priority"] is False


def test_high_score_takes_the_flag_branch(db, crm_data, fake_llm):
    fake_llm(
        LeadScore(score=91.0, priority=Priority.high, reasoning="VP champion, budget approved.")
    )
    deal_id = crm_data["deal"].id

    result = run(db, deal_id)

    assert result["flagged"] is True
    activity = (
        db.query(Activity)
        .filter(Activity.deal_id == deal_id, Activity.type == ActivityType.agent_generated)
        .one()
    )
    assert activity.meta["flagged_high_priority"] is True


def test_low_score_skips_the_flag_branch(db, crm_data, fake_llm):
    fake_llm(LeadScore(score=20.0, priority=Priority.low, reasoning="No engagement yet."))

    result = run(db, crm_data["deal"].id)

    assert result.get("flagged") is not True


def test_context_includes_contact_title_and_history(db, crm_data, fake_llm):
    from app.agents.context import load_deal_context

    context = load_deal_context(db, crm_data["deal"].id)

    assert context["contact"]["title"] == "VP of Operations"
    assert context["company"]["industry"] == "Manufacturing"
    assert context["deal"]["stage"] == "proposal"
