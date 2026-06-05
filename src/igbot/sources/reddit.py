"""Reddit source via PRAW.

Pulls top posts from configured subreddits for a time window, filters by score
and media type, and yields :class:`Candidate` objects.

Terms note (verified): the free Reddit API tier is **non-commercial**. A
commercial product needs written approval + a paid contract, and since 2025 even
personal apps need pre-approval. Redistributing Reddit content may itself breach
the Developer Terms. Surface this to the operator — don't bury it.
"""

from __future__ import annotations

from typing import Iterator

from ..config import Config, Feed
from ..models import Candidate

# v.redd.it / reddit-hosted videos need the yt-dlp+ffmpeg audio merge.
_VIDEO_DOMAINS = ("v.redd.it",)
_IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp")


class RedditSource:
    name = "reddit"

    def __init__(self, config: Config):
        import praw

        creds = config.reddit_credentials()
        if not creds["client_id"] or not creds["client_secret"]:
            raise RuntimeError(
                "Reddit credentials missing. Set REDDIT_CLIENT_ID / "
                "REDDIT_CLIENT_SECRET (see .env.example)."
            )
        kwargs = dict(
            client_id=creds["client_id"],
            client_secret=creds["client_secret"],
            user_agent=config.reddit_user_agent,
        )
        # Username/password only needed for user-context (script) apps.
        if creds["username"] and creds["password"]:
            kwargs["username"] = creds["username"]
            kwargs["password"] = creds["password"]
        self.reddit = praw.Reddit(**kwargs)
        self.reddit.read_only = True

    def fetch(self, feed: Feed) -> Iterator[Candidate]:
        for sub in feed.subreddits:
            for post in self.reddit.subreddit(sub).top(
                time_filter=feed.time_window, limit=None
            ):
                cand = self._to_candidate(post, feed)
                if cand is None:
                    continue
                if cand.score < feed.min_score:
                    continue
                if cand.media_type not in feed.media_types:
                    continue
                yield cand

    def _to_candidate(self, post, feed: Feed) -> Candidate | None:
        media_type, url = self._extract_media(post)
        if media_type is None:
            return None
        return Candidate(
            source=self.name,
            source_post_id=post.id,
            media_type=media_type,
            source_url=url,
            permalink=f"https://www.reddit.com{post.permalink}",
            author=str(post.author) if post.author else "[deleted]",
            title=post.title or "",
            score=int(post.score),
            target_accounts=list(feed.target_accounts),
        )

    @staticmethod
    def _extract_media(post) -> tuple[str | None, str]:
        # Reddit-hosted video: pass the *post* permalink to yt-dlp, which knows
        # how to find and merge the separate audio stream.
        if getattr(post, "is_video", False) or (
            getattr(post, "domain", "") in _VIDEO_DOMAINS
        ):
            return "video", f"https://www.reddit.com{post.permalink}"

        url = getattr(post, "url", "") or ""
        lower = url.lower().split("?")[0]
        if lower.endswith(_IMAGE_EXTS):
            return "image", url
        # i.redd.it / imgur direct images sometimes lack an ext; treat known hosts.
        if any(h in url for h in ("i.redd.it", "i.imgur.com")):
            return "image", url
        return None, ""
