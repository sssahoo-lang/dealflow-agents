from fastapi import APIRouter
from pydantic import BaseModel

from app.agents.follow_up import graph as follow_up
from app.agents.llm import describe_anthropic_error
from app.agents.nl_query import graph as nl_query
from app.api.deps import CurrentUser, DbSession
from app.services.deal_service import get_deal
from app.services.errors import AgentUnavailable

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


def _run_agent(fn, *args):
    """Runs an agent graph, translating a real-provider failure into the
    app's own AgentUnavailable rather than an anthropic.AnthropicError
    leaking out of a route handler as a bare 500.

    `anthropic` is imported here, not at module scope, for the same reason
    llm.py keeps it local: routes that only ever run against the stub
    provider (the whole test suite, by default) shouldn't need the package
    importable to be exercised.
    """
    import anthropic

    try:
        return fn(*args)
    except anthropic.AnthropicError as e:
        raise AgentUnavailable(describe_anthropic_error(e)) from e


@router.post("/follow-up", response_model=FollowUpResponse)
def draft_follow_up(db: DbSession, user: CurrentUser, payload: FollowUpRequest):
    get_deal(db, user, payload.deal_id)  # enforces ownership before the agent runs
    result = _run_agent(follow_up.run, db, payload.deal_id)
    return FollowUpResponse(
        activity_id=result["activity_id"],
        subject=result["subject"],
        body=result["body"],
    )


@router.post("/query", response_model=QueryResponse)
def query_crm(db: DbSession, user: CurrentUser, payload: QueryRequest):
    result = _run_agent(nl_query.run, db, user, payload.question)
    return QueryResponse(
        answer=result["answer"], tool_calls=result.get("tool_calls", [])
    )
