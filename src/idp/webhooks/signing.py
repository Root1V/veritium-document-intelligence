"""Standard Webhooks signatures (https://www.standardwebhooks.com):
``webhook-signature: v1,<base64(HMAC-SHA256(key, "{id}.{timestamp}.{body}"))>``
where the key is the base64 part of a ``whsec_…`` secret. A header can carry
several space-separated signatures (key rotation); a receiver accepts the
message if any of them matches. Verification must use the raw body bytes."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time

SECRET_PREFIX = "whsec_"
DEFAULT_TOLERANCE_SECONDS = 5 * 60


def generate_secret() -> str:
    return SECRET_PREFIX + base64.b64encode(secrets.token_bytes(24)).decode()


def _key(secret: str) -> bytes:
    return base64.b64decode(secret.removeprefix(SECRET_PREFIX))


def sign(secret: str, msg_id: str, timestamp: int, body: bytes) -> str:
    to_sign = f"{msg_id}.{timestamp}.".encode() + body
    digest = hmac.new(_key(secret), to_sign, hashlib.sha256).digest()
    return "v1," + base64.b64encode(digest).decode()


def verify(
    secret: str, msg_id: str, timestamp: str, signature_header: str, body: bytes, *, tolerance: int = DEFAULT_TOLERANCE_SECONDS, now: int | None = None
) -> bool:
    try:
        ts = int(timestamp)
    except ValueError:
        return False
    if abs((now if now is not None else int(time.time())) - ts) > tolerance:
        return False
    expected = sign(secret, msg_id, ts, body).encode()
    return any(hmac.compare_digest(expected, candidate.encode()) for candidate in signature_header.split())
