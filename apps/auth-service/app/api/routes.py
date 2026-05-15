from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.user import User
from app.schemas.user import AuthResponse, UserLoginRequest, UserOut, UserRegisterRequest, VerifyResponse
from app.services.auth import create_access_token, decode_access_token, hash_password, verify_password
from prometheus_client import Counter

router = APIRouter()

auth_register_total = Counter("auth_register_total", "Total user registration attempts")
auth_login_total = Counter("auth_login_total", "Total user login attempts")
auth_verify_total = Counter("auth_verify_total", "Total auth token verification requests")


def _bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing authorization token")
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authorization header")
    return authorization.split(" ", 1)[1].strip()


def _to_user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        first_name=user.first_name,
        last_name=user.last_name,
        email=user.email,
        organization_name=user.organization_name,
    )


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/auth/register", response_model=AuthResponse)
def register(payload: UserRegisterRequest, db: Session = Depends(get_db)) -> AuthResponse:
    auth_register_total.inc()
    if (
        not payload.first_name.strip()
        or not payload.last_name.strip()
        or not payload.organization_name.strip()
        or not payload.password.strip()
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="All fields must be present and non-empty"
        )
    existing = db.scalar(select(User).where(User.email == payload.email.lower()))
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email is already registered")

    user = User(
        first_name=payload.first_name.strip(),
        last_name=payload.last_name.strip(),
        email=payload.email.lower(),
        password_hash=hash_password(payload.password),
        organization_name=payload.organization_name.strip(),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_access_token(user.id, user.email, user.organization_name)
    return AuthResponse(access_token=token, user=_to_user_out(user))


@router.post("/auth/login", response_model=AuthResponse)
def login(payload: UserLoginRequest, db: Session = Depends(get_db)) -> AuthResponse:
    auth_login_total.inc()
    if not payload.password.strip():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
    user = db.scalar(select(User).where(User.email == payload.email.lower()))
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

    token = create_access_token(user.id, user.email, user.organization_name)
    return AuthResponse(access_token=token, user=_to_user_out(user))


@router.get("/auth/me", response_model=UserOut)
def me(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> UserOut:
    token = _bearer_token(authorization)
    try:
        claims = decode_access_token(token)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token") from exc
    user_id = claims.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    return _to_user_out(user)


@router.get("/auth/verify", response_model=VerifyResponse)
def verify(authorization: str | None = Header(default=None)) -> VerifyResponse:
    auth_verify_total.inc()
    token = _bearer_token(authorization)
    try:
        claims = decode_access_token(token)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token") from exc
    user_id = claims.get("sub")
    email = claims.get("email")
    organization_name = claims.get("organization_name")
    if not user_id or not email or not organization_name:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    return VerifyResponse(valid=True, user_id=user_id, email=email, organization_name=organization_name)
