def test_register_and_login(client):
    resp = client.post(
        "/auth/register",
        json={"email": "new@test.com", "password": "pw", "full_name": "New User"},
    )
    assert resp.status_code == 201
    assert resp.json()["role"] == "rep"

    resp = client.post("/auth/login", json={"email": "new@test.com", "password": "pw"})
    assert resp.status_code == 200
    assert resp.json()["access_token"]


def test_duplicate_email_rejected(client):
    payload = {"email": "dup@test.com", "password": "pw", "full_name": "Dup"}
    assert client.post("/auth/register", json=payload).status_code == 201
    assert client.post("/auth/register", json=payload).status_code == 409


def test_wrong_password_rejected(client, users):
    resp = client.post("/auth/login", json={"email": "rep@test.com", "password": "nope"})
    assert resp.status_code == 401


def test_me_requires_token(client, users, token):
    assert client.get("/auth/me").status_code == 401
    resp = client.get("/auth/me", headers=token("rep@test.com"))
    assert resp.status_code == 200
    assert resp.json()["email"] == "rep@test.com"
