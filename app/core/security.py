from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(
    subject: str, uid: int | None = None, role: str | None = None
) -> str:
    """Mint an access token.

    `uid` and `role` are carried for consumers that validate this token but have
    no access to the users table -- the planned Java analytics service can't
    resolve an email to an id or a role, so it can't scope a query without them.
    Python still authenticates off `sub`, so adding these changes nothing here.
    """
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.access_token_expire_minutes
    )
    claims: dict[str, object] = {"sub": subject, "exp": expire}
    if uid is not None:
        claims["uid"] = uid
    if role is not None:
        claims["role"] = role
    return jwt.encode(claims, settings.jwt_secret, settings.jwt_algorithm)


def decode_access_token(token: str) -> str | None:
    try:
        payload = jwt.decode(token, settings.jwt_secret, [settings.jwt_algorithm])
    except JWTError:
        return None
    return payload.get("sub")
