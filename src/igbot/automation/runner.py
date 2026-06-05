"""Hands-off scheduled posting.

Two entry points, meant to run on GitHub Actions crons:

  * ``harvest``  (daily)        — pull the top N posts from each Reddit feed,
                                   download/normalize, upload to the public host,
                                   and append them to a queue.
  * ``post_next`` (every 2 h)   — publish the oldest queued item to its routed
                                   Instagram account.

The runners are ephemeral (wiped between runs), so the queue and the dedup set
live in the R2 bucket (``state/queue.json`` / ``state/seen.json``), not SQLite.

Each subreddit feed lists its ``target_accounts``, so "which subreddit → which
Instagram account" is just configuration.
"""

from __future__ import annotations

import logging

from ..config import Config
from ..media import download_and_normalize
from ..media.host import build_host
from ..media.overlay import apply_overlay, has_overlay
from ..publish.instagram import InstagramPublisher, PublishError, RateLimitError
from ..sources.reddit import RedditSource

log = logging.getLogger("igbot.automation")

_QUEUE = "queue.json"
_SEEN = "seen.json"
_SEEN_CAP = 5000  # keep the dedup set from growing without bound


def harvest(config: Config, host=None, source_factory=None) -> list[str]:
    """Refill the queue with the top posts from each Reddit feed. Returns the
    post ids added this run."""
    host = host or build_host(config.host)
    make_source = source_factory or (lambda cfg: RedditSource(cfg))

    seen = list(host.get_json(_SEEN, default=[]) or [])
    seen_set = set(seen)
    queue = list(host.get_json(_QUEUE, default=[]) or [])
    count = config.automation.harvest_count
    added: list[str] = []

    source = None
    for feed in config.feeds:
        if feed.source != "reddit":
            continue
        if source is None:
            source = make_source(config)
        n = 0
        for cand in source.fetch(feed):
            if n >= count:
                break
            if cand.source_post_id in seen_set:
                continue
            try:
                info = download_and_normalize(
                    cand.source_url, cand.media_type,
                    config.work_dir, cand.source_post_id,
                )
                local = str(info.path)
                if config.automation.brand_overlay and has_overlay(config.brand):
                    local = str(apply_overlay(
                        local, cand.media_type, config.brand, config.work_dir))
                public_url = host.upload(local)
            except Exception as exc:  # one bad post shouldn't end the harvest
                log.warning("harvest skip %s: %s", cand.source_post_id, exc)
                continue

            caption = cand.title or ""
            if config.automation.caption_suffix:
                caption = f"{caption}\n\n{config.automation.caption_suffix}".strip()
            as_reel = bool(info.reels_eligible) if cand.media_type == "video" else True
            for account_id in feed.target_accounts:
                queue.append({
                    "post_id": cand.source_post_id,
                    "account_id": account_id,
                    "media_type": cand.media_type,
                    "public_url": public_url,
                    "caption": caption,
                    "as_reel": as_reel,
                    "permalink": cand.permalink,
                    "author": cand.author,
                })
            seen_set.add(cand.source_post_id)
            seen.append(cand.source_post_id)
            added.append(cand.source_post_id)
            n += 1
            log.info("queued %s -> %s", cand.source_post_id, feed.target_accounts)

    host.put_json(_QUEUE, queue)
    host.put_json(_SEEN, seen[-_SEEN_CAP:])
    log.info("harvest added %d post(s); queue length now %d", len(added), len(queue))
    return added


def post_next(config: Config, host=None, publisher_factory=None) -> str | None:
    """Publish the oldest queued item to its account. Returns the IG media id,
    or None if the queue is empty / the run was deferred."""
    import os

    host = host or build_host(config.host)
    queue = list(host.get_json(_QUEUE, default=[]) or [])
    if not queue:
        log.info("queue empty — nothing to post")
        return None

    entry = queue[0]
    account_id = entry["account_id"]
    token = Config.ig_token(account_id)
    ig_user_id = config.ig_user_id(account_id)
    if not token or not ig_user_id:
        # Misconfigured account would block the queue forever — drop and move on.
        log.error("no credentials for account %s (set IGBOT_TOKEN_%s / "
                  "IGBOT_IGID_%s) — dropping this item",
                  account_id, account_id.upper(), account_id.upper())
        host.put_json(_QUEUE, queue[1:])
        return None

    if publisher_factory:
        publisher = publisher_factory(ig_user_id, token)
    else:
        publisher = InstagramPublisher(
            ig_user_id, token,
            graph_host=config.instagram.graph_host,
            api_version=config.instagram.api_version,
        )

    try:
        media_id = publisher.publish(
            entry["public_url"], entry["media_type"],
            entry.get("caption", ""), as_reel=entry.get("as_reel", True),
        )
    except RateLimitError as exc:
        # Daily cap reached — leave the item in place and try again next run.
        log.warning("rate limited, leaving item queued: %s", exc)
        return None
    except PublishError as exc:
        # Bad media / permanent error — drop it so it can't block the queue.
        log.error("dropping unpublishable item %s: %s", entry.get("post_id"), exc)
        host.put_json(_QUEUE, queue[1:])
        return None

    host.put_json(_QUEUE, queue[1:])
    log.info("posted %s to %s as media %s",
             entry.get("post_id"), account_id, media_id)
    return media_id
