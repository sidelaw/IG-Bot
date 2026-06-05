"""Milestone 1 pipeline: fetch -> dedup -> download+normalize -> enqueue."""

from __future__ import annotations

import logging

from .config import Config
from .db import Store
from .media import download_and_normalize
from .sources.reddit import RedditSource

log = logging.getLogger("igbot.pipeline")


def run_fetch(config: Config, limit: int | None = None) -> list[int]:
    """Run every configured feed. Returns the candidate ids enqueued this run."""
    store = Store(config.db_path)
    max_posts = limit if limit is not None else config.max_posts_per_run
    enqueued: list[int] = []

    sources = {"reddit": RedditSource}

    # Sync configured accounts so routing FKs resolve.
    known_accounts = {acct.id for acct in config.accounts}
    for acct in config.accounts:
        store.upsert_account(acct.id, acct.username, acct.auth_flow)

    try:
        for feed in config.feeds:
            src_cls = sources.get(feed.source)
            if src_cls is None:
                log.warning("skipping feed %s: source %r not implemented",
                            feed.name, feed.source)
                continue
            source = src_cls(config)
            log.info("feed %s (%s): fetching", feed.name, feed.source)

            for cand in source.fetch(feed):
                if len(enqueued) >= max_posts:
                    log.info("hit max_posts_per_run=%d", max_posts)
                    return enqueued
                if store.is_seen(cand.source, cand.source_post_id):
                    continue

                # Drop routing to accounts that aren't configured, so a typo'd
                # target_account can't trip a routing FK and abort the run.
                unknown = [a for a in cand.target_accounts if a not in known_accounts]
                if unknown:
                    log.warning("feed %s: unknown target account(s) %s — skipping "
                                "those routes", feed.name, unknown)
                cand.target_accounts = [a for a in cand.target_accounts
                                        if a in known_accounts]

                try:
                    info = download_and_normalize(
                        cand.source_url, cand.media_type,
                        config.work_dir, cand.source_post_id,
                    )
                    cand.local_path = info.path
                    cand.duration = info.duration
                    cand.width = info.width
                    cand.height = info.height
                    cand.has_audio = info.has_audio
                    cand.reels_eligible = info.reels_eligible
                    cand_id = store.add_candidate(cand)
                except Exception as exc:  # one bad post shouldn't kill the run
                    log.warning("skipping %s: %s", cand.source_post_id, exc)
                    continue

                # Mark seen only after a successful enqueue, so a transient
                # download failure doesn't permanently bury a recoverable post.
                store.mark_seen(cand.source, cand.source_post_id)
                enqueued.append(cand_id)
                log.info(
                    "queued #%d %s by u/%s | %s%s | audio=%s reels=%s",
                    cand_id, cand.source_post_id, cand.author, cand.media_type,
                    f" {cand.duration:.0f}s" if cand.duration else "",
                    cand.has_audio, cand.reels_eligible,
                )
    finally:
        store.close()
    return enqueued
