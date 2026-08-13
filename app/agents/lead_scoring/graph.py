import json
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.agents.context import load_deal_context
from app.agents.llm import get_chat_model
from app.models.activity import Activity
from app.models.deal import Deal
from app.models.enums import ActivityType, Priority

HIGH_PRIORITY_THRESHOLD = 80.0

SYSTEM_PROMPT = """You are a CRM lead-scoring analyst. Score this deal 0-100 on how \
likely it is to close and how much attention it deserves now.

Weigh: deal value, company industry fit, seniority of the primary contact (a VP or \
C-level champion matters more than an individual contributor), and recency/depth of \
activity history. A deal with no activity and no named contact should score low \
regardless of value.

Return a score, a priority band, and two or three sentences of reasoning a sales rep \
could act on."""


class LeadScore(BaseModel):
    score: float = Field(ge=0, le=100)
    priority: Priority
    reasoning: str


class LeadScoringState(TypedDict, total=False):
    deal_id: int
    context: dict
    score: float
    priority: str
    reasoning: str
    flagged: bool


def build_graph(db: Session):
    def fetch_context(state: LeadScoringState) -> LeadScoringState:
        return {"context": load_deal_context(db, state["deal_id"])}

    def score_lead(state: LeadScoringState) -> LeadScoringState:
        model = get_chat_model("lead_scoring").with_structured_output(LeadScore)
        result = model.invoke(
            [
                ("system", SYSTEM_PROMPT),
                ("human", json.dumps(state["context"], indent=2)),
            ]
        )
        return {
            "score": result.score,
            "priority": result.priority.value,
            "reasoning": result.reasoning,
        }

    def flag_high_priority(state: LeadScoringState) -> LeadScoringState:
        return {"flagged": True}

    def persist_result(state: LeadScoringState) -> LeadScoringState:
        deal = db.get(Deal, state["deal_id"])
        deal.score = state["score"]
        deal.priority = Priority(state["priority"])
        db.add(
            Activity(
                deal_id=deal.id,
                type=ActivityType.agent_generated,
                subject=f"Lead score: {state['score']:.0f} ({state['priority']})",
                body=state["reasoning"],
                meta={
                    "agent": "lead_scoring",
                    "score": state["score"],
                    "priority": state["priority"],
                    "flagged_high_priority": state.get("flagged", False),
                },
            )
        )
        db.commit()
        return {}

    def route_on_score(state: LeadScoringState) -> str:
        return "flag" if state["score"] >= HIGH_PRIORITY_THRESHOLD else "persist"

    graph = StateGraph(LeadScoringState)
    graph.add_node("fetch_context", fetch_context)
    graph.add_node("score_lead", score_lead)
    graph.add_node("flag_high_priority", flag_high_priority)
    graph.add_node("persist_result", persist_result)

    graph.add_edge(START, "fetch_context")
    graph.add_edge("fetch_context", "score_lead")
    graph.add_conditional_edges(
        "score_lead",
        route_on_score,
        {"flag": "flag_high_priority", "persist": "persist_result"},
    )
    graph.add_edge("flag_high_priority", "persist_result")
    graph.add_edge("persist_result", END)
    return graph.compile()


def run(db: Session, deal_id: int) -> dict:
    return build_graph(db).invoke({"deal_id": deal_id})
