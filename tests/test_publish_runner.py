"""Runner orchestration: env token -> upload -> publish -> DB status + log."""

from __future__ import annotations

from pathlib import Path

import pytest

from igbot.config import (
    Account,
    Config,
    HostConfig,
    InstagramConfig,
)
from igbot.db import Store
from igbot.models import Candidate
from igbot.publish import runner


def _config(tmp_path) -> Config:
    return Config(
        mode="review", max_posts_per_run=20,
        work_dir=tmp_path, db_path=tmp_path / "t.db",
        reddit_user_agent="ua",
        feeds=[], accounts=[Account(id="acct_main", username="m")],
        host=HostConfig(bucket="b", public_base_url="https://cdn"),
        instagram=InstagramConfig(),
    )


class _FakePublisher:
    last = None

    def __init__(self, *a, **kw):
        _FakePublisher.last = self
        self.published = None

    def publish(self, public_url, media_type, caption="", *, as_reel=True, **kw):
        self.published = dict(url=public_url, media_type=media_type,
                              caption=caption, as_reel=as_reel)
        return "media_777"


def _seed(cfg, **overrides) -> int:
    store = Store(cfg.db_path)
    store.upsert_account("acct_main", "m")
    c = Candidate(
        source="reddit", source_post_id="p1", media_type="video",
        source_url="u", title="great lawn", target_accounts=["acct_main"],
        local_path=Path("/tmp/p1.mp4"), duration=12.0,
        width=1080, height=1920, has_audio=True, reels_eligible=True,
    )
    for k, v in overrides.items():
        setattr(c, k, v)
    cid = store.add_candidate(c)
    store.close()
    return cid


def _patch(monkeypatch):
    monkeypatch.setattr(runner, "build_host",
                        lambda cfg: type("H", (), {"upload": lambda s, p: "https://cdn/p1.mp4"})())
    monkeypatch.setattr(runner, "InstagramPublisher", _FakePublisher)
    monkeypatch.setenv("IGBOT_TOKEN_ACCT_MAIN", "tok")
    monkeypatch.setenv("IGBOT_IGID_ACCT_MAIN", "ig123")


def test_publish_updates_status_and_log(tmp_path, monkeypatch):
    cfg = _config(tmp_path)
    cid = _seed(cfg)
    _patch(monkeypatch)

    media_id = runner.publish_candidate(cfg, cid, "acct_main")
    assert media_id == "media_777"
    assert _FakePublisher.last.published["as_reel"] is True   # reels-eligible
    assert _FakePublisher.last.published["caption"] == "great lawn"

    store = Store(cfg.db_path)
    row = store.get_candidate(cid)
    assert row["status"] == "published"
    log = store.conn.execute(
        "SELECT * FROM publish_log WHERE candidate_id = ?", (cid,)
    ).fetchone()
    assert log["status"] == "published" and log["ig_media_id"] == "media_777"
    store.close()


def test_non_reels_video_published_as_feed(tmp_path, monkeypatch):
    cfg = _config(tmp_path)
    cid = _seed(cfg, reels_eligible=False, duration=200.0)
    _patch(monkeypatch)
    runner.publish_candidate(cfg, cid, "acct_main")
    assert _FakePublisher.last.published["as_reel"] is False


def test_missing_token_raises(tmp_path, monkeypatch):
    cfg = _config(tmp_path)
    cid = _seed(cfg)
    monkeypatch.delenv("IGBOT_TOKEN_ACCT_MAIN", raising=False)
    from igbot.publish.instagram import PublishError
    with pytest.raises(PublishError):
        runner.publish_candidate(cfg, cid, "acct_main")
