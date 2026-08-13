import json
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.agents.context import load_deal_context
from app.agents.llm import get_chat_model
from app.models.activity import Activity
from app.models.enums import ActivityType

SYSTEM_PROMPT = """You draft follow-up emails for a sales rep. Given a deal's context \
and recent activity, write the next follow-up message.

Match tone to the pipeline stage: exploratory and low-pressure at 'new' or \
'qualified', concrete and next-step-oriented at 'proposal' or 'negotiation'.

Reference something specific from the activity history rather than sending a generic \
check-in. Keep it under 150 words. Never invent facts, commitments, prices, or dates \
that do not appear in the context."""


class Draft(BaseModel):
    subject: str
    body: str


class FollowUpState(TypedDict, total=False):
    deal_id: int
    context: dict
    subject: str
    body: str
    activity_id: int


def build_graph(db: Session):
    def fetch_context(state: FollowUpState) -> FollowUpState:
        return {"context": load_deal_context(db, state["deal_id"])}

    def draft_message(state: FollowUpState) -> FollowUpState:
        model = get_chat_model("follow_up").with_structured_output(Draft)
        result = model.invoke(
            [
                ("system", SYSTEM_PROMPT),
                ("human", json.dumps(state["context"], indent=2)),
            ]
        )
        return {"subject": result.subject, "body": result.body}

    def save_draft(state: FollowUpState) -> FollowUpState:
        # Saved as a draft only. Nothing is ever sent — a human reviews first.
        activity = Activity(
            deal_id=state["deal_id"],
            type=ActivityType.agent_generated,
            subject=state["subject"],
            body=state["body"],
            is_draft=True,
            meta={"agent": "follow_up"},
        )
        db.add(activity)
        db.commit()
        db.refresh(activity)
        return {"activity_id": activity.id}

    graph = StateGraph(FollowUpState)
    graph.add_node("fetch_context", fetch_context)
    graph.add_node("draft_message", draft_message)
    graph.add_node("save_draft", save_draft)

    graph.add_edge(START, "fetch_context")
    graph.add_edge("fetch_context", "draft_message")
    graph.add_edge("draft_message", "save_draft")
    graph.add_edge("save_draft", END)
    return graph.compile()


def run(db: Session, deal_id: int) -> dict:
    return build_graph(db).invoke({"deal_id": deal_id})
