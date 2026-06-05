"""Publish a queued candidate to one Instagram account (single happy path).

Ties together: token (env) -> public host upload -> IG container/publish ->
DB status + publish log.
"""

from __future__ import annotations

import logging
import os

from ..config import Config
from ..db import Store
from ..media.host import build_host
from ..media.overlay import apply_overlay, has_overlay
from .instagram import InstagramPublisher, PublishError

log = logging.getLogger("igbot.publish.runner")


def publish_candidate(config: Config, candidate_id: int, account_id: str) -> str:
    """Upload + publish one candidate to ``account_id``. Returns the IG media id."""
    account = config.account(account_id)
    if account is None:
        raise PublishError(f"account {account_id!r} not in config")

    token = Config.ig_token(account_id)
    if not token:
        raise PublishError(
            f"no token for {account_id}. Set IGBOT_TOKEN_{account_id.upper()} in env."
        )
    ig_user_id = os.environ.get(f"IGBOT_IGID_{account_id.upper()}", "")
    if not ig_user_id:
        raise PublishError(
            f"no IG user id for {account_id}. "
            f"Set IGBOT_IGID_{account_id.upper()} in env."
        )

    store = Store(config.db_path)
    try:
        row = store.get_candidate(candidate_id)
        if row is None:
            raise PublishError(f"candidate {candidate_id} not found")
        if not row["local_path"]:
            raise PublishError(f"candidate {candidate_id} has no normalized media")

        media_type = row["media_type"]
        # For video, publish as a Reel only when it's reels-eligible (5-90s, 9:16).
        # Otherwise it still publishes — as a regular feed video. Surface this.
        as_reel = bool(row["reels_eligible"]) if media_type == "video" else True
        if media_type == "video" and not as_reel:
            log.warning(
                "candidate %d is not Reels-eligible (dur=%s %sx%s); "
                "publishing as a feed video, not a Reel",
                candidate_id, row["duration"], row["width"], row["height"],
            )

        # Apply the brand overlay (material-edit transform) if the operator
        # enabled it for this candidate and a brand is configured.
        local_media = row["local_path"]
        if row["brand_overlay"]:
            if has_overlay(config.brand):
                local_media = str(apply_overlay(
                    local_media, media_type, config.brand, config.work_dir))
                log.info("applied brand overlay to candidate %d", candidate_id)
            else:
                # Toggle is on but [brand] has no text/logo — the operator asked
                # for a material edit they won't get. Surface it, don't bury it.
                log.warning("candidate %d has brand_overlay on but [brand] has no "
                            "text or logo configured — publishing WITHOUT an edit",
                            candidate_id)

        host = build_host(config.host)
        public_url = host.upload(local_media)
        log.info("uploaded candidate %d -> %s", candidate_id, public_url)

        publisher = InstagramPublisher(
            ig_user_id, token,
            graph_host=config.instagram.graph_host,
            api_version=config.instagram.api_version,
        )
        caption = row["caption"] or row["title"] or ""
        try:
            media_id = publisher.publish(public_url, media_type, caption,
                                         as_reel=as_reel)
        except PublishError as exc:
            store.log_publish(candidate_id, account_id, "error", detail=str(exc))
            raise
        store.set_status(candidate_id, "published")
        store.log_publish(candidate_id, account_id, "published", ig_media_id=media_id)
        log.info("published candidate %d to %s as media %s",
                 candidate_id, account_id, media_id)
        return media_id
    finally:
        store.close()
