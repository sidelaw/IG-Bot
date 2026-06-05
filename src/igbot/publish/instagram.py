"""Instagram content publishing via the Instagram API with Instagram Login.

Host ``graph.instagram.com``, Instagram-user access token, permissions
``instagram_business_basic`` + ``instagram_business_content_publish``.

The 3-step container dance (verified against Meta docs + 2026 guides):
    1. POST /{ig-user-id}/media         -> creation_id (container)
    2. GET  /{container-id}?fields=status_code  (poll IN_PROGRESS -> FINISHED)
    3. POST /{ig-user-id}/media_publish (creation_id) -> published media id

Rate limits are NOT hardcoded. ``content_publishing_limit`` is queried at
runtime (Meta's own numbers conflict: 25/50/100). Every response's
``X-App-Usage`` / ``X-Business-Use-Case-Usage`` headers are read and we back off
as they climb.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass

import requests

log = logging.getLogger("igbot.publish")

# Container status values (GET ?fields=status_code).
_DONE = "FINISHED"
_TERMINAL_BAD = {"ERROR", "EXPIRED"}

# Back off when any usage metric crosses this percentage of its ceiling.
_USAGE_BACKOFF_PCT = 90


class PublishError(RuntimeError):
    pass


class ContainerError(PublishError):
    pass


class RateLimitError(PublishError):
    pass


@dataclass
class PublishLimit:
    quota_usage: int
    quota_total: int | None   # None = endpoint didn't report a ceiling

    @property
    def remaining(self) -> int | None:
        """Remaining publishes, or None when the ceiling is unknown."""
        if self.quota_total is None:
            return None
        return max(self.quota_total - self.quota_usage, 0)

    @property
    def exhausted(self) -> bool:
        """True only when a known ceiling has been reached. Unknown != exhausted."""
        return self.quota_total is not None and self.quota_usage >= self.quota_total


class InstagramPublisher:
    def __init__(
        self,
        ig_user_id: str,
        access_token: str,
        *,
        graph_host: str = "graph.instagram.com",
        api_version: str = "v23.0",
        session: requests.Session | None = None,
    ):
        if not ig_user_id or not access_token:
            raise PublishError("ig_user_id and access_token are required")
        self.ig_user_id = ig_user_id
        self.token = access_token
        self.base = f"https://{graph_host}/{api_version}"
        self.session = session or requests.Session()

    # ----- low-level request with usage-header backoff -----

    def _request(self, method: str, path: str, **params) -> dict:
        params["access_token"] = self.token
        url = f"{self.base}/{path}"
        resp = self.session.request(method, url, params=params, timeout=60)
        self._respect_usage_headers(resp.headers)
        try:
            body = resp.json()
        except ValueError:
            body = {}
        if resp.status_code >= 400:
            err = body.get("error", {})
            msg = err.get("message", resp.text[:300])
            if resp.status_code == 429 or err.get("code") in (4, 17, 32, 613):
                raise RateLimitError(f"rate limited: {msg}")
            raise PublishError(f"{method} {path} -> {resp.status_code}: {msg}")
        return body

    @staticmethod
    def _respect_usage_headers(headers) -> None:
        """Sleep when X-App-Usage / X-Business-Use-Case-Usage approach the ceiling."""
        peak = 0
        raw = headers.get("X-App-Usage")
        if raw:
            try:
                # max(*values) would raise on an empty {} (Meta sends this at 0
                # usage); default(...) keeps it robust.
                peak = max([peak, *json.loads(raw).values()])
            except (ValueError, TypeError):
                pass
        raw = headers.get("X-Business-Use-Case-Usage")
        if raw:
            try:
                for entries in json.loads(raw).values():
                    for e in entries:
                        for k in ("call_count", "total_cputime", "total_time"):
                            peak = max(peak, e.get(k, 0))
            except (ValueError, TypeError, AttributeError):
                pass
        if peak >= _USAGE_BACKOFF_PCT:
            # Climb steeply as we near 100% so we don't trip a block.
            delay = min(60, (peak - _USAGE_BACKOFF_PCT + 1) * 5)
            log.warning("usage at %d%%, backing off %ds", peak, delay)
            time.sleep(delay)

    # ----- publishing limit (queried, never hardcoded) -----

    def publishing_limit(self) -> PublishLimit:
        body = self._request(
            "GET", f"{self.ig_user_id}/content_publishing_limit",
            fields="config,quota_usage",
        )
        data = (body.get("data") or [{}])[0]
        # A missing config/quota_total means "unknown ceiling" — NOT zero. Treating
        # it as 0 would refuse every publish on accounts the endpoint underreports.
        total = (data.get("config") or {}).get("quota_total")
        return PublishLimit(
            quota_usage=int(data.get("quota_usage", 0)),
            quota_total=int(total) if total is not None else None,
        )

    # ----- the 3-step dance -----

    def create_container(
        self,
        public_url: str,
        media_type: str,            # "image" | "video"
        caption: str = "",
        *,
        as_reel: bool = True,
        share_to_feed: bool = True,
    ) -> str:
        params: dict = {"caption": caption}
        if media_type == "image":
            params["image_url"] = public_url
        elif media_type == "video":
            params["video_url"] = public_url
            # REELS is the publishable video type; share_to_feed also shows it
            # in the feed. A clip outside Reels specs still publishes here but
            # IG serves it as a feed video, not on the Reels tab.
            params["media_type"] = "REELS" if as_reel else "VIDEO"
            if as_reel:
                params["share_to_feed"] = str(share_to_feed).lower()
        else:
            raise PublishError(f"unsupported media_type: {media_type!r}")

        body = self._request("POST", f"{self.ig_user_id}/media", **params)
        cid = body.get("id")
        if not cid:
            raise ContainerError(f"no container id in response: {body}")
        return cid

    def wait_for_container(
        self, container_id: str, *, interval: float = 30, timeout: float = 300
    ) -> None:
        """Poll until FINISHED. Video containers can take a while to process."""
        deadline = time.monotonic() + timeout
        while True:
            body = self._request("GET", container_id, fields="status_code,status")
            status = body.get("status_code")
            if status == _DONE:
                return
            if status in _TERMINAL_BAD:
                raise ContainerError(
                    f"container {container_id} failed: "
                    f"{status} {body.get('status', '')}"
                )
            if time.monotonic() >= deadline:
                raise ContainerError(
                    f"container {container_id} not ready after {timeout:.0f}s "
                    f"(last status {status})"
                )
            time.sleep(interval)

    def publish_container(self, container_id: str) -> str:
        body = self._request(
            "POST", f"{self.ig_user_id}/media_publish", creation_id=container_id
        )
        media_id = body.get("id")
        if not media_id:
            raise PublishError(f"no media id in publish response: {body}")
        return media_id

    # ----- orchestration -----

    def publish(
        self,
        public_url: str,
        media_type: str,
        caption: str = "",
        *,
        as_reel: bool = True,
        poll_interval: float = 30,
        poll_timeout: float = 300,
    ) -> str:
        """Full happy path. Refuses if the queried publishing limit is exhausted."""
        limit = self.publishing_limit()
        if limit.exhausted:
            raise RateLimitError(
                f"publishing limit reached ({limit.quota_usage}/{limit.quota_total})"
            )
        container = self.create_container(
            public_url, media_type, caption, as_reel=as_reel
        )
        if media_type == "video":
            self.wait_for_container(
                container, interval=poll_interval, timeout=poll_timeout
            )
        return self.publish_container(container)
