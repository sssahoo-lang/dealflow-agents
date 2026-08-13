from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from sqlalchemy.orm import Session

from app.agents.llm import get_chat_model
from app.agents.nl_query.tools import build_tools
from app.models.user import User

SYSTEM_PROMPT = """You answer questions about a sales CRM using the provided tools.

Always call a tool to get real data -- never guess at numbers, names, or totals. If \
the tools return nothing, say so plainly rather than inventing an answer.

Results are already filtered to what this user is permitted to see, so answer from \
exactly what the tools return. Keep answers short and concrete, citing specific deal \
names and figures."""

MAX_TOOL_ROUNDS = 5


class NLQueryState(TypedDict, total=False):
    question: str
    messages: Annotated[list[AnyMessage], add_messages]
    answer: str
    tool_calls: list[str]


def build_graph(db: Session, user: User):
    tools = build_tools(db, user)
    model = get_chat_model("nl_query").bind_tools(tools)
    tool_node = ToolNode(tools)

    def router(state: NLQueryState) -> NLQueryState:
        messages = state.get("messages") or [
            SystemMessage(SYSTEM_PROMPT),
            HumanMessage(state["question"]),
        ]
        response = model.invoke(messages)
        called = [tc["name"] for tc in getattr(response, "tool_calls", [])]
        return {
            "messages": messages + [response] if not state.get("messages") else [response],
            "tool_calls": state.get("tool_calls", []) + called,
        }

    def respond(state: NLQueryState) -> NLQueryState:
        return {"answer": state["messages"][-1].content}

    def should_continue(state: NLQueryState) -> str:
        last = state["messages"][-1]
        if getattr(last, "tool_calls", None):
            # Bound the loop so a confused model can't spin indefinitely.
            if len(state.get("tool_calls", [])) > MAX_TOOL_ROUNDS:
                return "respond"
            return "tools"
        return "respond"

    graph = StateGraph(NLQueryState)
    graph.add_node("router", router)
    graph.add_node("tools", tool_node)
    graph.add_node("respond", respond)

    graph.add_edge(START, "router")
    graph.add_conditional_edges(
        "router", should_continue, {"tools": "tools", "respond": "respond"}
    )
    graph.add_edge("tools", "router")
    graph.add_edge("respond", END)
    return graph.compile()


def run(db: Session, user: User, question: str) -> dict:
    return build_graph(db, user).invoke({"question": question})
