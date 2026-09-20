"""Evidence sink port. Real implementation (S3) is supplied by P4; local dev uses disk."""

from __future__ import annotations

import os
import uuid
from typing import Protocol


class EvidenceSink(Protocol):
    def save(self, merchant: str, content: bytes, content_type: str) -> str:
        """Persist evidence bytes and return an opaque evidence_key."""


class LocalDiskEvidenceSink:
    """Dev-only sink. Writes under ./.evidence/. Never use in the deployed environment."""

    def __init__(self, root: str = ".evidence") -> None:
        self.root = root
        os.makedirs(root, exist_ok=True)

    def save(self, merchant: str, content: bytes, content_type: str) -> str:
        ext = "png" if content_type == "image/png" else "bin"
        key = f"{merchant}/{uuid.uuid4().hex}.{ext}"
        path = os.path.join(self.root, key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(content)
        return key


class S3EvidenceSink:
    """Deployed-environment sink (WP-01 AC-01-04). Each Fargate task's
    container is ephemeral, so evidence must leave the box before the task
    exits; the returned `evidence_key` is the S3 object key, not a
    presigned URL, since export/redaction rules for evidence access are a
    WP-07+ concern out of this package's scope.
    """

    def __init__(self, bucket: str, client: S3ClientProtocol | None = None) -> None:
        self.bucket = bucket
        if client is None:
            import boto3

            client = boto3.client("s3")
        self._client = client

    def save(self, merchant: str, content: bytes, content_type: str) -> str:
        ext = "png" if content_type == "image/png" else "bin"
        key = f"{merchant}/{uuid.uuid4().hex}.{ext}"
        self._client.put_object(Bucket=self.bucket, Key=key, Body=content, ContentType=content_type)
        return key


class S3ClientProtocol(Protocol):
    def put_object(self, *, Bucket: str, Key: str, Body: bytes, ContentType: str) -> object: ...


def build_evidence_sink() -> EvidenceSink:
    """Composition-root selection: S3 when `PROOFPATH_EVIDENCE_BUCKET` is
    set (the deployed Fargate task), local disk otherwise (unchanged local
    dev/test behavior). Never chosen implicitly inside a connector.
    """
    bucket = os.environ.get("PROOFPATH_EVIDENCE_BUCKET", "")
    if bucket:
        return S3EvidenceSink(bucket)
    return LocalDiskEvidenceSink()
