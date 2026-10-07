"""Object storage port + its only Phase 0 adapter (S3-compatible / MinIO).

This is the one file that changes when swapping MinIO for real S3/GCS in
production — callers depend only on ``ObjectStore``.
"""

from __future__ import annotations

from typing import BinaryIO, Protocol

import boto3
from botocore.client import Config as BotoConfig

from idp.config import Settings


class ObjectStore(Protocol):
    def put(self, key: str, data: bytes | BinaryIO, content_type: str = "application/octet-stream") -> None: ...

    def get(self, key: str) -> bytes: ...

    def key_for(self, *, tenant: str, case_id: str, document_id: str, filename: str) -> str: ...


class S3ObjectStore:
    """Adapter over an S3-compatible endpoint (MinIO locally, real S3/GCS later)."""

    def __init__(self, settings: Settings) -> None:
        self._bucket = settings.storage_bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.storage_endpoint_url,
            aws_access_key_id=settings.storage_access_key,
            aws_secret_access_key=settings.storage_secret_key,
            region_name=settings.storage_region,
            config=BotoConfig(signature_version="s3v4"),
        )

    def ensure_bucket(self) -> None:
        existing = {b["Name"] for b in self._client.list_buckets().get("Buckets", [])}
        if self._bucket not in existing:
            self._client.create_bucket(Bucket=self._bucket)

    def put(self, key: str, data: bytes | BinaryIO, content_type: str = "application/octet-stream") -> None:
        body = data if isinstance(data, (bytes, bytearray)) else data.read()
        self._client.put_object(Bucket=self._bucket, Key=key, Body=body, ContentType=content_type)

    def get(self, key: str) -> bytes:
        resp = self._client.get_object(Bucket=self._bucket, Key=key)
        return resp["Body"].read()

    def key_for(self, *, tenant: str, case_id: str, document_id: str, filename: str) -> str:
        # `tenant` costs nothing to include now and avoids a storage-key
        # migration when multi-tenancy lands (roadmap Fase 1+ item 5).
        return f"{tenant}/{case_id}/{document_id}/{filename}"
