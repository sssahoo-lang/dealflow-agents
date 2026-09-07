from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentUser, DbSession
from app.core.keys import jwks
from app.core.security import create_access_token, hash_password, verify_password
from app.models.user import User
from app.schemas.auth import LoginRequest, RegisterRequest, Token, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])

# Not under /auth: RFC 8615 puts discovery documents at a fixed well-known path,
# and a verifier should be able to find it from the issuer's origin alone.
jwks_router = APIRouter(tags=["auth"])


@jwks_router.get("/.well-known/jwks.json")
def jwks_document():
    """The public half of the signing key, for anyone verifying our tokens.

    Deliberately unauthenticated. A public key is public -- requiring a token to
    fetch the key needed to validate tokens is a circular dependency, and the
    analytics service must be able to come up before anybody has logged in.
    """
    return jwks()


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(db: DbSession, payload: RegisterRequest):
    if db.query(User).filter(User.email == payload.email).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")
    user = User(
        email=payload.email,
        hashed_password=hash_password(payload.password),
        full_name=payload.full_name,
        role=payload.role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/login", response_model=Token)
def login(db: DbSession, payload: LoginRequest):
    user = db.query(User).filter(User.email == payload.email).first()
    if user is None or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password")
    return Token(
        access_token=create_access_token(
            user.email, uid=user.id, role=user.role.value
        )
    )


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser):
    return user
