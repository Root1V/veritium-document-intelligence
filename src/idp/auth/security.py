"""Password hashing and JWT issuance/verification for the internal-tool
login (replaces the static ``x-api-key`` used before the frontend module —
see the plan's 'Login real, no una pantalla decorativa' decision).

HS256 with a single shared secret is adequate here: one backend process
issues and verifies its own tokens, no second service needs to verify them
independently. Move to asymmetric keys only if that changes.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta

from jose import JWTError, jwt
from passlib.context import CryptContext

from idp.config import Settings

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return _pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return _pwd_context.verify(password, password_hash)


def create_access_token(settings: Settings, *, user_id: uuid.UUID) -> str:
    expires_at = datetime.now(UTC) + timedelta(minutes=settings.jwt_expiration_minutes)
    payload = {"sub": str(user_id), "exp": expires_at}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def create_client_token(settings: Settings, *, user_id: uuid.UUID, client_id: str) -> str:
    """A connected system's token (VRT-65): short-lived, and it names the
    client, so a revoked or rotated client stops working at once."""
    now = datetime.now(UTC)
    # iat with sub-second precision: a token issued right after a rotation must not look older than it.
    payload = {"sub": str(user_id), "cid": client_id, "iat": now.timestamp(), "exp": now + timedelta(minutes=settings.api_client_token_minutes)}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_claims(settings: Settings, token: str) -> dict | None:
    """The claims of a valid, unexpired token, or None."""
    try:
        return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError:
        return None


def hash_client_secret(secret: str) -> str:
    """Client secrets are random and long: a plain sha256 is enough (no bcrypt cost on every token request)."""
    return hashlib.sha256(secret.encode()).hexdigest()
