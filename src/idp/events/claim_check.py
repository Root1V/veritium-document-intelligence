"""Claim-check (VRT-49): a command never carries a document's bytes, only
where to fetch them. Only the configured prefixes are fetched — anything
else would let a sender make Veritium read arbitrary URLs (SSRF)."""

from __future__ import annotations

import asyncio
from urllib.parse import urlparse

import httpx

from idp.config import Settings
from idp.storage.object_store import S3ObjectStore


class ClaimCheckError(ValueError):
    pass


def allowed(url: str, prefixes: list[str]) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in ("s3", "https", "http") or ".." in parsed.path.split("/"):
        return False
    return any(url.startswith(p) for p in prefixes)


async def fetch(settings: Settings, url: str) -> bytes:
    if not allowed(url, settings.claim_check_allowed_prefixes):
        raise ClaimCheckError(f"{url}: no está en un origen permitido para leer documentos")
    max_bytes = settings.claim_check_max_file_mb * 1024 * 1024
    try:
        if url.startswith("s3://"):
            bucket, _, key = url.removeprefix("s3://").partition("/")
            return await asyncio.to_thread(S3ObjectStore(settings).get_at, bucket, key, max_bytes=max_bytes)
        async with httpx.AsyncClient(follow_redirects=False, timeout=30.0) as client, client.stream("GET", url) as response:
            response.raise_for_status()
            content = bytearray()
            async for chunk in response.aiter_bytes():
                content += chunk
                if len(content) > max_bytes:
                    raise ValueError(f"pesa más de {settings.claim_check_max_file_mb} MB")
            return bytes(content)
    except ClaimCheckError:
        raise
    except Exception as exc:  # not found, no permission, too large, network
        raise ClaimCheckError(f"{url}: no se pudo leer ({type(exc).__name__}: {exc})") from exc
