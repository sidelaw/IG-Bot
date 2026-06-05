"""Reddit source via the **public RSS feed** — no API key, no authentication.

Fetches ``https://www.reddit.com/r/{subreddit}/top.rss`` (an Atom feed of the
subreddit's top posts), parses it with the stdlib XML parser, and yields
:class:`Candidate` objects. Because ``top.rss`` is already sorted by top, posts
are yielded in that order; the feed carries no score, so ``min_score`` is not
applied here.

Media handling:
  * direct images (i.redd.it / imgur / *.jpg|png|webp) are used as-is;
  * reddit-hosted video / galleries / external video hosts are downloaded by
    passing the **post permalink** to yt-dlp (which locates and merges the
    separate v.redd.it audio stream).

Terms note (still applies): redistributing Reddit content for a commercial
product is not cleanly permitted by Reddit's terms. RSS removes the API-key
requirement, not the content-licensing question. Eyes open. (Not legal advice.)
"""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from typing import Iterator

import requests

from ..config import Config, Feed
from ..models import Candidate

log = logging.getLogger("igbot.sources.reddit")

_NS = {"a": "http://www.w3.org/2005/Atom"}
_IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp")
_IMAGE_HOSTS = ("i.redd.it", "i.imgur.com")
_VIDEO_HINTS = ("v.redd.it", "/gallery/", "youtube.com", "youtu.be",
                "streamable.com", "redgifs.com")
_HREF = re.compile(r'href="([^"]+)"')


class RedditSource:
    name = "reddit"

    def __init__(self, config: Config, session: requests.Session | None = None):
        # A descriptive User-Agent avoids Reddit's default-client throttling.
        self.user_agent = config.reddit_user_agent or "igbot/0.1 (rss reader)"
        self.session = session or requests.Session()
        self.session.headers.setdefault("User-Agent", self.user_agent)
        self.limit = 25

    def fetch(self, feed: Feed) -> Iterator[Candidate]:
        for sub in feed.subreddits:
            url = f"https://www.reddit.com/r/{sub}/top.rss"
            params = {"t": feed.time_window, "limit": self.limit}
            try:
                resp = self.session.get(url, params=params, timeout=30)
            except requests.RequestException as exc:
                log.warning("reddit rss fetch failed for r/%s: %s", sub, exc)
                continue
            if resp.status_code != 200:
                log.warning("reddit rss r/%s -> HTTP %s", sub, resp.status_code)
                continue
            for cand in self._parse(resp.content, feed):
                if feed.media_types and cand.media_type not in feed.media_types:
                    continue
                yield cand

    def _parse(self, xml_bytes: bytes, feed: Feed) -> Iterator[Candidate]:
        try:
            root = ET.fromstring(xml_bytes)
        except ET.ParseError as exc:
            log.warning("reddit rss parse error: %s", exc)
            return
        for entry in root.findall("a:entry", _NS):
            raw_id = (entry.findtext("a:id", default="", namespaces=_NS) or "")
            post_id = raw_id.split("_", 1)[1] if "_" in raw_id else raw_id
            if not post_id:
                continue
            title = entry.findtext("a:title", default="", namespaces=_NS) or ""
            link_el = entry.find("a:link", _NS)
            permalink = link_el.get("href", "") if link_el is not None else ""
            author = entry.findtext("a:author/a:name", default="", namespaces=_NS) or ""
            author = author.lstrip("/")
            if author.startswith("u/"):
                author = author[2:]
            content = entry.findtext("a:content", default="", namespaces=_NS) or ""

            media_type, media_url = self._media_from(content, permalink)
            if media_type is None:
                continue
            yield Candidate(
                source=self.name,
                source_post_id=post_id,
                media_type=media_type,
                source_url=media_url,
                permalink=permalink,
                author=author or "[deleted]",
                title=title,
                score=0,  # not available in RSS; top.rss is already top-sorted
                target_accounts=list(feed.target_accounts),
            )

    @staticmethod
    def _media_from(content_html: str, permalink: str) -> tuple[str | None, str]:
        hrefs = _HREF.findall(content_html)
        # Direct image -> use it as-is.
        for h in hrefs:
            low = h.lower().split("?")[0]
            if any(host in h for host in _IMAGE_HOSTS) or low.endswith(_IMAGE_EXTS):
                return "image", h
        # Reddit-hosted video / gallery / external video -> hand the permalink to
        # yt-dlp (it finds + merges the separate v.redd.it audio).
        for h in hrefs:
            if any(hint in h for hint in _VIDEO_HINTS):
                return "video", permalink or h
        return None, ""   # self/text post or unrecognized media -> skip
