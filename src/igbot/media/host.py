"""Public media host.

Instagram fetches media by cURLing a public URL, so every local file must be
uploaded to a publicly reachable host before publishing. This module uploads to
an S3-compatible bucket (AWS S3 *or* Cloudflare R2 — R2 speaks the S3 API, you
just set ``endpoint_url``) and returns the public URL.

Credentials come from the environment (the standard ``AWS_ACCESS_KEY_ID`` /
``AWS_SECRET_ACCESS_KEY``), never from config or the repo.
"""

from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Protocol

from ..config import HostConfig


class MediaHost(Protocol):
    def upload(self, local_path: str | Path) -> str:
        """Upload a file and return its public URL."""
        ...


def _content_type(path: Path) -> str:
    if path.suffix.lower() in (".jpg", ".jpeg"):
        return "image/jpeg"
    if path.suffix.lower() == ".mp4":
        return "video/mp4"
    return mimetypes.guess_type(str(path))[0] or "application/octet-stream"


class S3Host:
    """Upload to an S3-compatible bucket (AWS S3 or Cloudflare R2)."""

    def __init__(self, cfg: HostConfig):
        if not cfg.bucket:
            raise RuntimeError("host.bucket is not configured")
        if not cfg.public_base_url:
            raise RuntimeError(
                "host.public_base_url is required — Instagram needs a public URL"
            )
        self.cfg = cfg
        try:
            import boto3
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "boto3 is required for the S3 host. `pip install boto3`."
            ) from exc
        kwargs: dict = {}
        if cfg.endpoint_url:
            # R2 (or other S3-compatible): "auto" is a valid region here.
            kwargs["endpoint_url"] = cfg.endpoint_url
            kwargs["region_name"] = cfg.region or "auto"
        elif cfg.region and cfg.region != "auto":
            # AWS S3 rejects "auto"; only pass a real region, else let boto3 resolve.
            kwargs["region_name"] = cfg.region
        # Access keys come from the environment (boto3's default chain).
        self._client = boto3.client("s3", **kwargs)

    def _key(self, path: Path) -> str:
        prefix = self.cfg.key_prefix.strip("/")
        return f"{prefix}/{path.name}" if prefix else path.name

    def upload(self, local_path: str | Path) -> str:
        path = Path(local_path)
        key = self._key(path)
        self._client.upload_file(
            str(path), self.cfg.bucket, key,
            ExtraArgs={"ContentType": _content_type(path)},
        )
        base = self.cfg.public_base_url.rstrip("/")
        return f"{base}/{key}"


def build_host(cfg: HostConfig) -> MediaHost:
    if cfg.provider == "s3":
        return S3Host(cfg)
    raise RuntimeError(f"unknown host provider: {cfg.provider!r}")
