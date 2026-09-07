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


# --- token rejection paths ---------------------------------------------------


def test_malformed_token_is_rejected(client):
    resp = client.get("/auth/me", headers={"Authorization": "Bearer not-a-jwt"})

    assert resp.status_code == 401


def test_token_signed_with_a_different_key_is_rejected(client, users):
    """Under RS256 the only way to forge is to hold another private key -- and
    holding one gets an attacker nothing, because the CRM verifies against its
    own published key, not against whatever signed the token."""
    from datetime import datetime, timedelta, timezone

    from cryptography.hazmat.primitives.asymmetric import rsa
    from jose import jwt

    from app.config import settings
    from app.core.keys import SigningKey

    attacker = SigningKey(rsa.generate_private_key(public_exponent=65537, key_size=2048))
    forged = jwt.encode(
        {
            "sub": "admin@test.com",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=60),
        },
        attacker.private_pem,
        settings.jwt_algorithm,
        headers={"kid": attacker.kid},
    )

    resp = client.get("/auth/me", headers={"Authorization": f"Bearer {forged}"})

    assert resp.status_code == 401


def test_expired_token_is_rejected(client, users):
    from datetime import datetime, timedelta, timezone

    from jose import jwt

    from app.config import settings
    from app.core.keys import signing_key

    expired = jwt.encode(
        {
            "sub": "admin@test.com",
            "exp": datetime.now(timezone.utc) - timedelta(minutes=1),
        },
        signing_key().private_pem,
        settings.jwt_algorithm,
    )

    resp = client.get("/auth/me", headers={"Authorization": f"Bearer {expired}"})

    assert resp.status_code == 401


def test_valid_token_for_a_deleted_user_is_rejected(client, db, users, token):
    """The token stays cryptographically valid after the user row is gone."""
    headers = token("other@test.com")
    db.delete(users["other"])
    db.commit()

    assert client.get("/auth/me", headers=headers).status_code == 401
