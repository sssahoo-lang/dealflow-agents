"""The JWT secret is a cross-service contract, not just a local setting.

python-jose signs happily with a short key; jjwt (Java) refuses to construct one
below RFC 7518's 256-bit floor and the analytics service won't boot. That
asymmetry means a too-short secret looks fine in Python and breaks the other
service -- so the floor is validated here as well, to fail on the side where
someone is most likely to set it.
"""

import pytest
from pydantic import ValidationError

from app.config import MIN_JWT_SECRET_BYTES, Settings


def test_the_shipped_default_satisfies_the_floor():
    """A fresh clone must be able to start BOTH services without editing .env."""
    assert len(Settings().jwt_secret.encode()) >= MIN_JWT_SECRET_BYTES


def test_a_short_secret_is_rejected_with_an_actionable_message():
    with pytest.raises(ValidationError) as excinfo:
        Settings(jwt_secret="too-short")

    message = str(excinfo.value)
    assert str(MIN_JWT_SECRET_BYTES) in message
    # The message must explain the cross-service consequence, not just the rule.
    assert "Java" in message


def test_the_floor_matches_rfc_7518():
    """256 bits. If this ever changes, the Java constant must change with it."""
    assert MIN_JWT_SECRET_BYTES * 8 == 256


def test_a_secret_exactly_at_the_floor_is_accepted():
    assert Settings(jwt_secret="a" * MIN_JWT_SECRET_BYTES)
