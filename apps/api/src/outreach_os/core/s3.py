"""S3 client — MinIO-compatible, with presigned-URL helpers.

We use boto3 with the MinIO endpoint configured in settings. Buckets are
auto-created on first use. The drafts bucket is separate from the general
S3 bucket so we can apply different lifecycle policies later.

The client is process-wide. `reset_for_tests` clears the singleton so
tests can swap the bucket name between runs.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from outreach_os.core.config import get_settings

log = logging.getLogger(__name__)


class S3Error(RuntimeError):
    """Wraps any boto3 / botocore failure."""


def _build_client() -> Any:
    s = get_settings()
    if not s.s3_endpoint_url:
        # In CI we might not have S3 at all; let callers fail loudly.
        raise S3Error("S3_ENDPOINT_URL is not configured")
    return boto3.client(
        "s3",
        endpoint_url=s.s3_endpoint_url,
        aws_access_key_id=s.s3_access_key,
        aws_secret_access_key=s.s3_secret_key.get_secret_value(),
        region_name=s.s3_region,
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


@lru_cache(maxsize=1)
def get_s3_client() -> Any:
    return _build_client()


def reset_for_tests() -> None:
    """Clear the cached client — call from test fixtures that change settings."""
    get_s3_client.cache_clear()


def ensure_bucket(bucket: str) -> None:
    """Create the bucket if it doesn't exist. Idempotent."""
    client = get_s3_client()
    try:
        client.head_bucket(Bucket=bucket)
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in ("404", "NoSuchBucket", "NotFound"):
            try:
                client.create_bucket(Bucket=bucket)
                log.info("created S3 bucket %s", bucket)
            except ClientError as c_exc:
                raise S3Error(f"failed to create bucket {bucket}: {c_exc}") from c_exc
        else:
            raise S3Error(f"failed to head bucket {bucket}: {exc}") from exc


def upload_text(
    bucket: str,
    key: str,
    body: str,
    *,
    content_type: str = "text/markdown; charset=utf-8",
) -> None:
    """Upload a text body to `s3://bucket/key`. Creates the bucket if needed."""
    ensure_bucket(bucket)
    client = get_s3_client()
    try:
        client.put_object(
            Bucket=bucket,
            Key=key,
            Body=body.encode("utf-8"),
            ContentType=content_type,
        )
    except ClientError as exc:
        raise S3Error(f"upload failed for s3://{bucket}/{key}: {exc}") from exc


def download_text(bucket: str, key: str) -> str:
    """Fetch a text body from `s3://bucket/key`."""
    client = get_s3_client()
    try:
        resp = client.get_object(Bucket=bucket, Key=key)
    except ClientError as exc:
        raise S3Error(f"download failed for s3://{bucket}/{key}: {exc}") from exc
    return resp["Body"].read().decode("utf-8")


def presign_get(bucket: str, key: str, *, ttl: int | None = None) -> str:
    """Return a presigned GET URL with a short TTL. Used by the drafts API."""
    s = get_settings()
    client = get_s3_client()
    return client.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": key},
        ExpiresIn=ttl or s.s3_presign_ttl,
    )


def build_draft_key(tenant_id: str, draft_id: str, *, step_number: int) -> str:
    """Stable key layout: drafts/{tenant}/{draft}/{step}.md
    Step is included so regenerations don't overwrite the previous body
    if the user re-runs generation for the same (campaign, lead, step)."""
    return f"drafts/{tenant_id}/{draft_id}/step-{step_number}.md"
