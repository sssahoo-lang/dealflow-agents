"""These are the security tests for the NL query agent.

RBAC lives inside the tool implementations, so a compromised or confused model must
not be able to widen its own access. Every test here asserts that property.
"""

import pytest

from app.agents.nl_query.tools import ROW_LIMIT, build_tools
from app.models.deal import Deal


@pytest.fixture
def tools_for(db, crm_data, users):
    def _build(role: str) -> dict:
        return {t.name: t for t in build_tools(db, users[role])}

    return _build


def test_rep_query_is_scoped_to_own_deals(tools_for):
    results = tools_for("rep")["query_deals"].invoke({})

    assert {d["name"] for d in results} == {"Acme rollout"}


def test_admin_query_sees_all_deals(tools_for):
    results = tools_for("admin")["query_deals"].invoke({})

    assert len(results) == 2


def test_rep_cannot_widen_scope_via_filters(tools_for, crm_data):
    """Even filtering for the other rep's exact deal returns nothing."""
    results = tools_for("rep")["query_deals"].invoke({"stage": "new"})

    assert all(d["name"] != "Other rep deal" for d in results)


def test_stage_filter_works(tools_for):
    results = tools_for("admin")["query_deals"].invoke({"stage": "proposal"})

    assert len(results) == 1
    assert results[0]["stage"] == "proposal"


def test_min_value_filter_works(tools_for):
    results = tools_for("admin")["query_deals"].invoke({"min_value": 100000})

    assert len(results) == 1
    assert results[0]["name"] == "Acme rollout"


def test_contacts_are_scoped_to_owner(tools_for):
    assert len(tools_for("rep")["query_contacts"].invoke({})) == 1
    assert len(tools_for("other")["query_contacts"].invoke({})) == 0


def test_title_filter_is_a_safe_substring_match(tools_for):
    results = tools_for("rep")["query_contacts"].invoke({"title_contains": "VP"})

    assert len(results) == 1
    assert results[0]["title"] == "VP of Operations"


def test_aggregate_stats_scoped_by_role(tools_for):
    rep_stats = tools_for("rep")["aggregate_stats"].invoke({"group_by": "stage"})
    admin_stats = tools_for("admin")["aggregate_stats"].invoke({"group_by": "stage"})

    assert sum(s["deal_count"] for s in rep_stats) == 1
    assert sum(s["deal_count"] for s in admin_stats) == 2


def test_aggregate_stats_rejects_arbitrary_group_by(tools_for):
    """The model cannot pick a grouping column that isn't allowlisted."""
    result = tools_for("admin")["aggregate_stats"].invoke({"group_by": "owner_id"})

    assert "error" in result[0]


def test_row_limit_is_enforced(db, users, crm_data, tools_for):
    company_id = crm_data["company"].id
    db.add_all(
        [
            Deal(
                name=f"Bulk deal {i}",
                company_id=company_id,
                owner_id=users["admin"].id,
                value=100,
            )
            for i in range(ROW_LIMIT + 20)
        ]
    )
    db.commit()

    results = tools_for("admin")["query_deals"].invoke({})

    assert len(results) == ROW_LIMIT
