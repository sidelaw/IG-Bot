"""X (Twitter) source via the API v2 recent-search endpoint.

Pay-per-use since Feb 2026 (~$0.005 per post read) — every run costs money, so
each query is fetched once with the configured ``max_results`` ceiling.

Reading is a sanctioned paid activity; **redistributing** the content carries
its own terms (see CLAUDE.md / README). Surface this; don't bury it.

Verified API specifics:
  - GET {api_base}/tweets/search/recent, App-only Bearer auth, last 7 days.
  - tweet.fields=public_metrics -> like_count / retweet_count / ... for scoring.
  - expansions=attachments.media_keys,author_id; media.fields=type,url,variants.
  - Photos carry media.url; VIDEO/animated_gif media.url is null — the mp4 lives
    in media.variants (pick the highest-bit_rate video/mp4 entry).
"""

from __future__ import annotations

import logging
from typing import Iterator

import requests

from ..config import Config, Feed
from ..models import Candidate

log = logging.getLogger("igbot.sources.x")

_TWEET_FIELDS = "public_metrics,created_at,author_id"
_MEDIA_FIELDS = "type,url,variants,duration_ms,width,height,preview_image_url"
_EXPANSIONS = "attachments.media_keys,author_id"


class XSource:
    name = "x"

    def __init__(self, config: Config, session: requests.Session | None = None):
        token = config.x_bearer_token()
        if not token:
            raise RuntimeError(
                "X bearer token missing. Set X_BEARER_TOKEN (see .env.example)."
            )
        self.cfg = config.x
        self.session = session or requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {token}"})

    def fetch(self, feed: Feed) -> Iterator[Candidate]:
        for query in feed.queries:
            payload = self._search(query)
            media_by_key = {m["media_key"]: m
                            for m in payload.get("includes", {}).get("media", [])}
            users = {u["id"]: u
                     for u in payload.get("includes", {}).get("users", [])}
            for tweet in payload.get("data", []):
                cand = self._to_candidate(tweet, media_by_key, users, feed)
                if cand is None:
                    continue
                if cand.score < feed.min_score:
                    continue
                if cand.media_type not in feed.media_types:
                    continue
                yield cand

    def _search(self, query: str) -> dict:
        full_query = f"({query}) {self.cfg.query_suffix}".strip()
        params = {
            "query": full_query,
            "max_results": max(10, min(self.cfg.max_results, 100)),
            "tweet.fields": _TWEET_FIELDS,
            "media.fields": _MEDIA_FIELDS,
            "expansions": _EXPANSIONS,
            "user.fields": "username",
        }
        resp = self.session.get(
            f"{self.cfg.api_base}/tweets/search/recent", params=params, timeout=30
        )
        if resp.status_code != 200:
            raise RuntimeError(
                f"X search failed ({resp.status_code}): {resp.text[:300]}"
            )
        return resp.json()

    def _to_candidate(self, tweet, media_by_key, users, feed: Feed) -> Candidate | None:
        keys = (tweet.get("attachments") or {}).get("media_keys") or []
        media = next((media_by_key[k] for k in keys if k in media_by_key), None)
        if media is None:
            return None
        media_type, url = self._extract_media(media)
        if media_type is None:
            return None

        metrics = tweet.get("public_metrics") or {}
        score = int(metrics.get("like_count", 0)) + int(metrics.get("retweet_count", 0))
        author = users.get(tweet.get("author_id", ""), {})
        username = author.get("username", "")
        permalink = (f"https://x.com/{username}/status/{tweet['id']}"
                     if username else f"https://x.com/i/web/status/{tweet['id']}")

        return Candidate(
            source=self.name,
            source_post_id=tweet["id"],
            media_type=media_type,
            source_url=url,
            permalink=permalink,
            author=username or tweet.get("author_id", ""),
            title=tweet.get("text", ""),
            score=score,
            target_accounts=list(feed.target_accounts),
        )

    @staticmethod
    def _extract_media(media: dict) -> tuple[str | None, str]:
        mtype = media.get("type")
        if mtype == "photo":
            url = media.get("url") or ""
            if not url:
                return None, ""
            # Request the original-resolution asset.
            sep = "&" if "?" in url else "?"
            return "image", f"{url}{sep}name=orig"
        if mtype in ("video", "animated_gif"):
            url = _best_mp4_variant(media.get("variants") or [])
            return ("video", url) if url else (None, "")
        return None, ""


def _best_mp4_variant(variants: list[dict]) -> str:
    """Highest-bitrate progressive mp4. (animated_gif variants report bit_rate 0.)"""
    mp4s = [v for v in variants if v.get("content_type") == "video/mp4" and v.get("url")]
    if not mp4s:
        return ""
    best = max(mp4s, key=lambda v: v.get("bit_rate", 0))
    return best["url"]
