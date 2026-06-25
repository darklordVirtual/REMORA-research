# Author: Stian Skogbrott
# License: Apache-2.0
"""S3-compatible storage adapter — AWS S3, MinIO, Cloudflare R2.

Requirements:
    pip install boto3
"""
from __future__ import annotations

from remora.adapters.storage import StorageAdapter


class S3Storage(StorageAdapter):
    """Store artifacts in an S3-compatible bucket.

    Works with AWS S3, MinIO (on-prem), and Cloudflare R2.

    Parameters
    ----------
    bucket:
        S3 bucket name.
    prefix:
        Key prefix for all objects (e.g. 'remora/artifacts/').
    endpoint_url:
        Custom endpoint for MinIO or R2. None for AWS S3.
    """

    def __init__(
        self,
        bucket: str,
        prefix: str = "",
        endpoint_url: str | None = None,
        region_name: str = "us-east-1",
    ):
        self._bucket = bucket
        self._prefix = prefix
        self._endpoint_url = endpoint_url
        self._region = region_name

    def _client(self):
        import boto3
        return boto3.client("s3", endpoint_url=self._endpoint_url, region_name=self._region)

    def _key(self, key: str) -> str:
        return f"{self._prefix}{key}" if self._prefix else key

    def put(self, key: str, data: bytes) -> None:
        self._client().put_object(Bucket=self._bucket, Key=self._key(key), Body=data)

    def get(self, key: str) -> bytes | None:
        try:
            resp = self._client().get_object(Bucket=self._bucket, Key=self._key(key))
            return resp["Body"].read()
        except self._client().exceptions.NoSuchKey:
            return None

    def exists(self, key: str) -> bool:
        try:
            self._client().head_object(Bucket=self._bucket, Key=self._key(key))
            return True
        except Exception:
            return False

    def list_keys(self, prefix: str = "") -> list[str]:
        full_prefix = self._key(prefix)
        paginator = self._client().get_paginator("list_objects_v2")
        keys = []
        for page in paginator.paginate(Bucket=self._bucket, Prefix=full_prefix):
            for obj in page.get("Contents", []):
                rel = obj["Key"]
                if self._prefix:
                    rel = rel[len(self._prefix):]
                keys.append(rel)
        return sorted(keys)
