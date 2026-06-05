"""Publish a queued candidate to one Instagram account (single happy path).

Ties together: token (env) -> public host upload -> IG container/publish ->
DB status + publish log.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from ..config import Config
from ..db import Store
from ..media.host import build_host
from ..media.overlay import apply_overlay, has_overlay
from .instagram import InstagramPublisher, PublishError

log = logging.getLogger("igbot.publish.runner")

_VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".webm", ".mkv"}
_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".heic"}


def publish_local_file(
    config: Config,
    file_path: str | Path,
    account_id: str = "acct_main",
    caption: str = "",
    brand_overlay: bool = False,
) -> str:
    """Publish a local video/image straight to Instagram (your own footage).

    Skips the fetch/review queue: normalize -> optional brand overlay -> upload
    to the public host -> IG publish. Returns the IG media id.
    """
    from ..media.downloader import _normalize_image, _normalize_video

    path = Path(file_path)
    if not path.exists():
        raise PublishError(f"file not found: {path}")

    token = Config.ig_token(account_id)
    ig_user_id = config.ig_user_id(account_id)
    if not token:
        raise PublishError(
            f"no token. Set IGBOT_TOKEN_{account_id.upper()} (your IG token).")
    if not ig_user_id:
        raise PublishError(
            f"no IG user id. Set it in config.toml (ig_user_id) or "
            f"IGBOT_IGID_{account_id.upper()}.")

    ext = path.suffix.lower()
    out_dir = Path(config.work_dir) / "normalized"
    out_dir.mkdir(parents=True, exist_ok=True)
    if ext in _VIDEO_EXTS:
        info = _normalize_video(path, out_dir, path.stem)
        media_type = "video"
        as_reel = bool(info.reels_eligible)
        if not as_reel:
            log.warning("not Reels-eligible (dur=%s %sx%s) — posting as a feed "
                        "video, not a Reel", info.duration, info.width, info.height)
    elif ext in _IMAGE_EXTS:
        info = _normalize_image(path, out_dir, path.stem)
        media_type, as_reel = "image", True
    else:
        raise PublishError(f"unsupported file type: {ext}")

    local_media = str(info.path)
    if brand_overlay and has_overlay(config.brand):
        local_media = str(apply_overlay(
            local_media, media_type, config.brand, config.work_dir))
        log.info("applied brand overlay")

    host = build_host(config.host)
    public_url = host.upload(local_media)
    log.info("uploaded -> %s", public_url)

    publisher = InstagramPublisher(
        ig_user_id, token,
        graph_host=config.instagram.graph_host,
        api_version=config.instagram.api_version,
    )
    media_id = publisher.publish(public_url, media_type, caption, as_reel=as_reel)
    log.info("published to %s as media %s", account_id, media_id)
    return media_id


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
    ig_user_id = config.ig_user_id(account_id)
    if not ig_user_id:
        raise PublishError(
            f"no IG user id for {account_id}. Set it in config.toml (ig_user_id) "
            f"or IGBOT_IGID_{account_id.upper()}."
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
