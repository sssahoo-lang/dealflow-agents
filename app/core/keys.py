"""The CRM's signing key, and the public half it publishes.

Why this file exists: the analytics service used to verify tokens with the same
HS256 secret the CRM signed with. Symmetric verification means every verifier is
also a *minter* -- a compromise of the read-only analytics service could forge an
admin token for the CRM, which inverts the whole point of giving that service a
SELECT-only database role.

Asymmetric signing removes the possibility rather than reducing it. The CRM holds
a private key and is the only thing that can mint; the analytics service fetches
the public half from `/.well-known/jwks.json` and can only verify. There is no
longer any signing material on that side to steal.

Key sourcing, in order:

1. `JWT_PRIVATE_KEY` -- a PKCS#8 PEM. What a real deployment sets.
2. Nothing -- generate an ephemeral keypair at startup.

The ephemeral path is what keeps `docker compose up` and a fresh clone working
with no setup, and it is safe in a way a committed dev key would not be: a
private key in the repository is a real finding, not a convenience. The cost is
that tokens do not survive a restart and that two API replicas would sign with
different keys -- see the README's limitations.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
from functools import lru_cache

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.config import settings

log = logging.getLogger(__name__)

# RFC 7518 s3.3 requires >= 2048 bits for RSASSA-PKCS1-v1_5.
MIN_RSA_KEY_BITS = 2048


def _b64u(raw: bytes) -> str:
    """base64url with no padding, as every JWK field is encoded (RFC 7515 App C)."""
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _int_to_b64u(value: int) -> str:
    return _b64u(value.to_bytes((value.bit_length() + 7) // 8, "big"))


class SigningKey:
    """One RSA keypair, plus the JWKS view of its public half."""

    def __init__(self, private_key: rsa.RSAPrivateKey) -> None:
        if private_key.key_size < MIN_RSA_KEY_BITS:
            raise ValueError(
                f"RSA key must be at least {MIN_RSA_KEY_BITS} bits "
                f"(got {private_key.key_size}); RFC 7518 requires it for RS256."
            )
        self._private = private_key
        self.private_pem = private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode()
        self.public_pem = private_key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode()

        numbers = private_key.public_key().public_numbers()
        self._n = _int_to_b64u(numbers.n)
        self._e = _int_to_b64u(numbers.e)
        self.kid = self._thumbprint()

    def _thumbprint(self) -> str:
        """RFC 7638 thumbprint: the kid is *derived* from the key, not assigned.

        This matters for rotation. A verifier that has cached the old key sees an
        unfamiliar kid, refetches, and finds the new one -- without anybody
        coordinating an identifier by hand, and without two distinct keys ever
        being able to collide on the same name.
        """
        canonical = json.dumps(
            {"e": self._e, "kty": "RSA", "n": self._n},
            separators=(",", ":"),
            sort_keys=True,
        )
        return _b64u(hashlib.sha256(canonical.encode()).digest())

    def public_jwk(self) -> dict[str, str]:
        """The public half only.

        Deliberately built field by field rather than by filtering a full JWK:
        an allowlist cannot leak `d`, `p` or `q` the way a denylist eventually
        does. This is served to anyone who asks, so it is worth the pedantry.
        """
        return {
            "kty": "RSA",
            "use": "sig",
            "alg": "RS256",
            "kid": self.kid,
            "n": self._n,
            "e": self._e,
        }


@lru_cache(maxsize=1)
def signing_key() -> SigningKey:
    """The process's signing key. Loaded once; cached for the process lifetime."""
    pem = settings.jwt_private_key.strip()
    if pem:
        loaded = serialization.load_pem_private_key(pem.encode(), password=None)
        if not isinstance(loaded, rsa.RSAPrivateKey):
            raise ValueError(
                "JWT_PRIVATE_KEY must be an RSA private key; RS256 is the only "
                f"algorithm this service signs with (got {type(loaded).__name__})."
            )
        return SigningKey(loaded)

    log.warning(
        "No JWT_PRIVATE_KEY set -- generating an ephemeral RSA keypair. Tokens "
        "will not survive a restart, and separate replicas would sign with "
        "different keys. Set JWT_PRIVATE_KEY for anything but local development."
    )
    return SigningKey(
        rsa.generate_private_key(public_exponent=65537, key_size=MIN_RSA_KEY_BITS)
    )


def jwks() -> dict[str, list[dict[str, str]]]:
    """The document served at /.well-known/jwks.json.

    A list with one entry today. It is a list because rotation is the reason this
    endpoint exists: publishing the new key alongside the old one is what lets
    tokens signed before a rotation keep verifying until they expire.
    """
    return {"keys": [signing_key().public_jwk()]}
