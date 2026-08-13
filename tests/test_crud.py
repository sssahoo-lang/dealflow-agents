def test_create_company_and_contact(client, users, token):
    headers = token("rep@test.com")
    company = client.post(
        "/companies", json={"name": "Globex", "industry": "Energy"}, headers=headers
    )
    assert company.status_code == 201

    contact = client.post(
        "/contacts",
        json={
            "first_name": "Mia",
            "last_name": "Chen",
            "title": "Director",
            "company_id": company.json()["id"],
        },
        headers=headers,
    )
    assert contact.status_code == 201
    assert contact.json()["owner_id"] == users["rep"].id


def test_create_deal_defaults_to_new_stage(client, crm_data, token):
    resp = client.post(
        "/deals",
        json={"name": "Fresh deal", "company_id": crm_data["company"].id, "value": 1000},
        headers=token("rep@test.com"),
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["stage"] == "new"
    # Agent-populated fields start empty.
    assert body["score"] is None
    assert body["priority"] is None


def test_cannot_create_deal_directly_in_won_stage_as_rep(client, crm_data, token):
    resp = client.post(
        "/deals",
        json={"name": "Sneaky", "company_id": crm_data["company"].id, "stage": "won"},
        headers=token("rep@test.com"),
    )
    assert resp.status_code == 403


def test_activity_filtering_by_deal(client, crm_data, token):
    headers = token("rep@test.com")
    deal_id = crm_data["deal"].id
    client.post(
        "/activities",
        json={"type": "call", "body": "Spoke with Dana", "deal_id": deal_id},
        headers=headers,
    )
    resp = client.get(f"/activities?deal_id={deal_id}", headers=headers)
    assert resp.status_code == 200
    assert len(resp.json()) == 1
    assert resp.json()[0]["body"] == "Spoke with Dana"


def test_missing_deal_returns_404(client, users, token):
    resp = client.get("/deals/9999", headers=token("admin@test.com"))
    assert resp.status_code == 404
