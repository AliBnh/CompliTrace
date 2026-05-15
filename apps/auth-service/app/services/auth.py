import os
from datetime import UTC, datetime, timedelta, timezone

from jose import JWTError, jwt
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

JWT_SECRET = os.getenv("AUTH_JWT_SECRET")
JWT_ALGORITHM = os.getenv("AUTH_JWT_ALGORITHM", "HS256")
JWT_EXPIRY_HOURS = int(os.getenv("AUTH_JWT_EXPIRY_HOURS", "24"))


def ensure_jwt_secret() -> None:
    if not JWT_SECRET:
        raise RuntimeError("AUTH_JWT_SECRET is required but not set")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)


def create_access_token(user_id: str, email: str, organization_name: str) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": user_id,
        "email": email,
        "organization_name": organization_name,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=JWT_EXPIRY_HOURS)).timestamp()),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except JWTError as exc:
        raise ValueError("Invalid or expired token") from exc
