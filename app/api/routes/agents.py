from fastapi import APIRouter
from pydantic import BaseModel

from app.agents.follow_up import graph as follow_up
from app.agents.nl_query import graph as nl_query
from app.api.deps import CurrentUser, DbSession
from app.services.deal_service import get_deal

router = APIRouter(prefix="/agents", tags=["agents"])


class FollowUpRequest(BaseModel):
    deal_id: int


class FollowUpResponse(BaseModel):
    activity_id: int
    subject: str
    body: str
    is_draft: bool = True


class QueryRequest(BaseModel):
    question: str


class QueryResponse(BaseModel):
    answer: str
    tool_calls: list[str]


@router.post("/follow-up", response_model=FollowUpResponse)
def draft_follow_up(db: DbSession, user: CurrentUser, payload: FollowUpRequest):
    get_deal(db, user, payload.deal_id)  # enforces ownership before the agent runs
    result = follow_up.run(db, payload.deal_id)
    return FollowUpResponse(
        activity_id=result["activity_id"],
        subject=result["subject"],
        body=result["body"],
    )


@router.post("/query", response_model=QueryResponse)
def query_crm(db: DbSession, user: CurrentUser, payload: QueryRequest):
    result = nl_query.run(db, user, payload.question)
    return QueryResponse(
        answer=result["answer"], tool_calls=result.get("tool_calls", [])
    )
