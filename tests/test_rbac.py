def test_rep_sees_only_own_deals(client, crm_data, token):
    resp = client.get("/deals", headers=token("rep@test.com"))
    assert resp.status_code == 200
    names = {d["name"] for d in resp.json()}
    assert names == {"Acme rollout"}


def test_admin_sees_all_deals(client, crm_data, token):
    resp = client.get("/deals", headers=token("admin@test.com"))
    assert len(resp.json()) == 2


def test_rep_cannot_read_another_reps_deal(client, crm_data, token):
    resp = client.get(
        f"/deals/{crm_data['other_deal'].id}", headers=token("rep@test.com")
    )
    assert resp.status_code == 403


def test_rep_cannot_close_deal(client, crm_data, token):
    resp = client.patch(
        f"/deals/{crm_data['deal'].id}",
        json={"stage": "won"},
        headers=token("rep@test.com"),
    )
    assert resp.status_code == 403
    assert "admin" in resp.json()["detail"].lower()


def test_admin_can_close_deal(client, crm_data, token):
    resp = client.patch(
        f"/deals/{crm_data['deal'].id}",
        json={"stage": "won"},
        headers=token("admin@test.com"),
    )
    assert resp.status_code == 200
    assert resp.json()["stage"] == "won"


def test_rep_can_advance_deal_within_pipeline(client, crm_data, token):
    resp = client.patch(
        f"/deals/{crm_data['deal'].id}",
        json={"stage": "negotiation"},
        headers=token("rep@test.com"),
    )
    assert resp.status_code == 200
    assert resp.json()["stage"] == "negotiation"
