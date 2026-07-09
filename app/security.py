"""Password hashing and JWT access tokens."""

import os
import warnings
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

_INSECURE_DEV_SECRET = "dev-only-insecure-secret-change-me"

ENVIRONMENT = os.environ.get("ENVIRONMENT", "development").strip().lower()

JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY", _INSECURE_DEV_SECRET)
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(
    os.environ.get("ACCESS_TOKEN_EXPIRE_MINUTES", str(60 * 24))
)

if JWT_SECRET_KEY == _INSECURE_DEV_SECRET:
    if ENVIRONMENT == "production":
        raise RuntimeError(
            "JWT_SECRET_KEY must be set when ENVIRONMENT=production. Generate "
            'one with: python -c "import secrets; print(secrets.token_urlsafe(48))"'
        )
    warnings.warn(
        "JWT_SECRET_KEY is not set; using an insecure default. "
        "Set the JWT_SECRET_KEY environment variable before deploying.",
        stacklevel=2,
    )


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), hashed_password.encode("utf-8"))


def create_access_token(user_id: str) -> str:
    expires_at = datetime.now(timezone.utc) + timedelta(
        minutes=ACCESS_TOKEN_EXPIRE_MINUTES
    )
    payload = {"sub": user_id, "exp": expires_at}
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> str:
    """Returns the user id from a valid token. Raises jwt.PyJWTError on failure."""
    payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
    return payload["sub"]
