"""Asymmetric signing, asserted as a security boundary rather than a setting.

The property under test is not "RS256 works". It is that **verifying a token no
longer implies being able to mint one**. The analytics service holds a
SELECT-only database role precisely so it cannot write anything the CRM trusts;
handing it a symmetric signing secret quietly gave back what the grant took away.

These tests fail if that boundary is ever walked back -- including by the
plausible-looking mistake of publishing a JWK straight from the private key.
"""

import json

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, rsa
from jose import jwt
from pydantic import ValidationError

from app.config import Settings, settings
from app.core.keys import MIN_RSA_KEY_BITS, SigningKey, signing_key
from app.core.security import create_access_token, decode_access_token


# --- the boundary itself -----------------------------------------------------


def test_the_published_jwk_carries_no_private_material():
    """The whole point. A leaked `d` would make the JWKS endpoint a key handout."""
    jwk = signing_key().public_jwk()

    # RFC 7518 s6.3.2 names every private RSA field. None may appear.
    for private_field in ("d", "p", "q", "dp", "dq", "qi", "oth"):
        assert private_field not in jwk, f"private field {private_field} published"

    assert set(jwk) == {"kty", "use", "alg", "kid", "n", "e"}


def test_a_token_verifies_against_the_public_half_alone():
    """A verifier holding only the JWKS can do its whole job."""
    token = create_access_token("rep@test.com", uid=7, role="rep")

    claims = jwt.decode(token, signing_key().public_pem, ["RS256"])

    assert claims["sub"] == "rep@test.com"
    assert claims["uid"] == 7 and claims["role"] == "rep"


def test_the_public_half_cannot_mint():
    """Signing with the published key must be impossible, not merely discouraged."""
    with pytest.raises(Exception):
        jwt.encode({"sub": "attacker"}, signing_key().public_pem, "RS256")


def test_a_token_signed_by_another_key_is_rejected():
    """A second RSA key is what a compromised verifier would have to forge with."""
    other = SigningKey(rsa.generate_private_key(public_exponent=65537, key_size=2048))
    forged = jwt.encode({"sub": "admin@test.com"}, other.private_pem, "RS256")

    assert decode_access_token(forged) is None


def test_a_symmetric_algorithm_is_refused_by_configuration():
    """Belt and braces: the algorithm confusion attack starts by allowing HS256."""
    with pytest.raises(ValidationError) as excinfo:
        Settings(jwt_algorithm="HS256")

    assert "mint" in str(excinfo.value)


# --- key identity and rotation ----------------------------------------------


def test_the_token_header_names_the_key():
    """Without a kid a verifier cannot tell rotation from forgery."""
    header = jwt.get_unverified_header(create_access_token("a@b.com"))

    assert header["alg"] == "RS256"
    assert header["kid"] == signing_key().kid


def test_the_kid_is_derived_from_the_key_not_assigned():
    """RFC 7638: same key -> same kid, different key -> different kid.

    Derivation is what makes rotation self-coordinating. Two processes given the
    same key agree on its name without being told, and no two distinct keys can
    collide on one.
    """
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    reloaded = serialization.load_pem_private_key(pem, password=None)

    assert SigningKey(key).kid == SigningKey(reloaded).kid
    assert SigningKey(key).kid != signing_key().kid


def test_the_thumbprint_uses_the_canonical_member_ordering():
    """A thumbprint over non-canonical JSON is a thumbprint nobody else computes."""
    key = SigningKey(rsa.generate_private_key(public_exponent=65537, key_size=2048))
    jwk = key.public_jwk()

    canonical = json.dumps(
        {"e": jwk["e"], "kty": jwk["kty"], "n": jwk["n"]},
        separators=(",", ":"),
        sort_keys=True,
    )
    import base64
    import hashlib

    expected = (
        base64.urlsafe_b64encode(hashlib.sha256(canonical.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    assert key.kid == expected


# --- key strength and type ---------------------------------------------------


def test_a_short_rsa_key_is_rejected():
    """RFC 7518 s3.3 sets 2048 bits as the floor for RS256."""
    weak = rsa.generate_private_key(public_exponent=65537, key_size=1024)

    with pytest.raises(ValueError) as excinfo:
        SigningKey(weak)

    assert str(MIN_RSA_KEY_BITS) in str(excinfo.value)


def test_a_non_rsa_key_is_rejected_with_an_actionable_message(monkeypatch):
    """An Ed25519 PEM loads fine and then fails cryptically at signing time."""
    key = ed25519.Ed25519PrivateKey.generate()
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    monkeypatch.setattr(settings, "jwt_private_key", pem)
    signing_key.cache_clear()

    try:
        with pytest.raises(ValueError) as excinfo:
            signing_key()
        assert "RS256" in str(excinfo.value)
    finally:
        signing_key.cache_clear()


def test_a_configured_key_is_used_in_preference_to_a_generated_one(monkeypatch):
    """What a real deployment does: supply the key, and expect it to be the one."""
    supplied = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = supplied.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    monkeypatch.setattr(settings, "jwt_private_key", pem)
    signing_key.cache_clear()

    try:
        assert signing_key().kid == SigningKey(supplied).kid
    finally:
        signing_key.cache_clear()
