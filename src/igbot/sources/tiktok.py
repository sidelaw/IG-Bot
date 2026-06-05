"""TikTok source — OPTIONAL, ISOLATED, OFF BY DEFAULT.

There is **no official API to download other people's TikToks**. The only path
is yt-dlp scraping, which:
  - breaks TikTok's Terms of Service, and
  - breaks whenever TikTok changes its site (expect this to rot).

So this module is walled off: it raises :class:`SourceDisabled` unless the
operator explicitly sets ``[tiktok] enabled = true``, and the pipeline isolates
its failures so a broken scrape never takes down the Reddit/X sources.

(Sourcing terms exposure applies here as everywhere — see CLAUDE.md.)
"""

from __future__ import annotations

import logging
from typing import Callable, Iterator

from ..config import Config, Feed
from ..models import Candidate
from .base import SourceDisabled

log = logging.getLogger("igbot.sources.tiktok")

# A lister maps a TikTok page URL -> a list of flat entry dicts (yt-dlp shape).
Lister = Callable[[str, int], list[dict]]


class TikTokSource:
    name = "tiktok"

    def __init__(self, config: Config, lister: Lister | None = None):
        if not config.tiktok.enabled:
            raise SourceDisabled(
                "tiktok source is disabled. It relies on yt-dlp scraping (breaks "
                "TikTok ToS and is fragile); set [tiktok] enabled = true to opt in."
            )
        self.cfg = config.tiktok
        self._list = lister or _ytdlp_list

    def fetch(self, feed: Feed) -> Iterator[Candidate]:
        for tag in feed.tags:
            url = _tag_url(tag)
            try:
                entries = self._list(url, self.cfg.max_per_tag)
            except Exception as exc:  # scraping is expected to break; degrade
                log.warning("tiktok scrape failed for %s (%s) — skipping", tag, exc)
                continue
            for entry in entries:
                cand = self._to_candidate(entry, feed)
                if cand is None:
                    continue
                if cand.score < feed.min_score:
                    continue
                if cand.media_type not in feed.media_types:
                    continue
                yield cand

    def _to_candidate(self, entry: dict, feed: Feed) -> Candidate | None:
        vid = entry.get("id")
        url = entry.get("webpage_url") or entry.get("url")
        if not vid or not url:
            return None
        score = int(entry.get("view_count") or entry.get("like_count") or 0)
        return Candidate(
            source=self.name,
            source_post_id=str(vid),
            media_type="video",       # TikTok is video-only for our purposes
            source_url=url,
            permalink=url,
            author=entry.get("uploader") or entry.get("channel") or "",
            title=entry.get("title") or entry.get("description") or "",
            score=score,
            target_accounts=list(feed.target_accounts),
        )


def _tag_url(tag: str) -> str:
    t = tag.strip()
    if t.startswith("@"):                       # a user feed
        return f"https://www.tiktok.com/{t}"
    return f"https://www.tiktok.com/tag/{t.lstrip('#')}"


def _ytdlp_list(url: str, limit: int) -> list[dict]:
    """Flat-list a TikTok page via yt-dlp. Best-effort; may return []."""
    from yt_dlp import YoutubeDL

    opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,       # list entries without downloading each
        "playlistend": limit,
        "ignoreerrors": True,
    }
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    if not info:
        return []
    return [e for e in (info.get("entries") or []) if e]
