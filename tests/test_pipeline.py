"""Pipeline robustness: dedup ordering and routing to unknown accounts."""

from __future__ import annotations

from pathlib import Path

from igbot import pipeline
from igbot.config import (
    Account,
    BrandConfig,
    Config,
    Feed,
    HostConfig,
    InstagramConfig,
    TikTokConfig,
    XConfig,
)
from igbot.db import Store
from igbot.media.downloader import MediaInfo
from igbot.models import Candidate


def _config(tmp_path, feed) -> Config:
    return Config(
        mode="review", max_posts_per_run=20,
        work_dir=tmp_path, db_path=tmp_path / "t.db",
        reddit_user_agent="ua", feeds=[feed],
        accounts=[Account(id="acct_main", username="m")],
        host=HostConfig(bucket="b", public_base_url="https://cdn"),
        instagram=InstagramConfig(), brand=BrandConfig(), x=XConfig(), tiktok=TikTokConfig(),
    )


class _FakeSource:
    name = "reddit"

    def __init__(self, config, cands):
        self._cands = cands

    def fetch(self, feed):
        yield from self._cands


def _video_info(tmp_path):
    return MediaInfo(path=tmp_path / "v.mp4", media_type="video", duration=10.0,
                     width=1080, height=1920, has_audio=True, reels_eligible=True)


def _patch(monkeypatch, cands, *, fail=False):
    monkeypatch.setattr(
        pipeline, "RedditSource", lambda cfg: _FakeSource(cfg, cands)
    )

    def fake_dl(url, mtype, work, pid):
        if fail:
            raise RuntimeError("transient download error")
        return _video_info(work)
    monkeypatch.setattr(pipeline, "download_and_normalize", fake_dl)


def _cand(targets):
    return Candidate(source="reddit", source_post_id="p1", media_type="video",
                     source_url="u", title="t", target_accounts=list(targets))


def test_unknown_target_account_does_not_crash(tmp_path, monkeypatch):
    feed = Feed(source="reddit", name="f", target_accounts=["acct_main", "typo"])
    cfg = _config(tmp_path, feed)
    _patch(monkeypatch, [_cand(["acct_main", "typo"])])

    ids = pipeline.run_fetch(cfg)          # must not raise on the FK
    assert len(ids) == 1

    store = Store(cfg.db_path)
    routes = store.conn.execute("SELECT account_id FROM routing").fetchall()
    assert [r["account_id"] for r in routes] == ["acct_main"]   # typo dropped
    store.close()


def test_midstream_source_failure_keeps_enqueued(tmp_path, monkeypatch):
    """A source that yields some candidates then blows up must keep the ones
    already queued (in the DB and in the returned list)."""
    feed = Feed(source="reddit", name="f", target_accounts=["acct_main"])
    cfg = _config(tmp_path, feed)

    class _Flaky:
        name = "reddit"
        def __init__(self, c): pass
        def fetch(self, feed):
            yield _cand(["acct_main"])             # gets queued
            raise RuntimeError("API blew up mid-stream")

    monkeypatch.setattr(pipeline, "RedditSource", _Flaky)
    monkeypatch.setattr(pipeline, "download_and_normalize",
                        lambda *a, **k: _video_info(tmp_path))

    ids = pipeline.run_fetch(cfg)
    assert len(ids) == 1                            # the pre-failure id survives
    store = Store(cfg.db_path)
    assert store.is_seen("reddit", "p1") is True
    store.close()


def test_failed_download_not_marked_seen(tmp_path, monkeypatch):
    feed = Feed(source="reddit", name="f", target_accounts=["acct_main"])
    cfg = _config(tmp_path, feed)
    _patch(monkeypatch, [_cand(["acct_main"])], fail=True)

    ids = pipeline.run_fetch(cfg)
    assert ids == []                       # nothing enqueued

    store = Store(cfg.db_path)
    # Not marked seen -> a later run can retry the recoverable post.
    assert store.is_seen("reddit", "p1") is False
    store.close()
