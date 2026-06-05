"""TikTok source: disabled by default, opt-in, URL building, and isolation."""

from __future__ import annotations

import pytest

from igbot.config import (
    Config,
    Feed,
    TikTokConfig,
    XConfig,
)
from igbot.sources.base import SourceDisabled
from igbot.sources.tiktok import TikTokSource, _tag_url


def _config(enabled: bool) -> Config:
    return Config(
        mode="review", max_posts_per_run=20, work_dir=".", db_path="x.db",
        reddit_user_agent="ua", feeds=[], accounts=[],
        host=None, instagram=None, brand=None, x=XConfig(),
        tiktok=TikTokConfig(enabled=enabled),
    )


def test_disabled_by_default():
    assert TikTokConfig().enabled is False
    with pytest.raises(SourceDisabled):
        TikTokSource(_config(enabled=False))


def test_tag_url_building():
    assert _tag_url("landscaping") == "https://www.tiktok.com/tag/landscaping"
    assert _tag_url("#lawn") == "https://www.tiktok.com/tag/lawn"
    assert _tag_url("@someuser") == "https://www.tiktok.com/@someuser"


def test_enabled_yields_candidates_with_injected_lister():
    entries = [
        {"id": "v1", "webpage_url": "https://www.tiktok.com/@a/video/v1",
         "uploader": "a", "title": "sod install", "view_count": 120000},
        {"id": "v2", "webpage_url": "https://www.tiktok.com/@b/video/v2",
         "uploader": "b", "title": "tiny", "view_count": 100},
        {"id": None, "webpage_url": None},     # malformed -> skipped
    ]
    src = TikTokSource(_config(enabled=True), lister=lambda url, n: entries)
    feed = Feed(source="tiktok", name="t", tags=["landscaping"], min_score=50000,
                media_types=["video"], target_accounts=["acct_main"])
    cands = list(src.fetch(feed))
    assert [c.source_post_id for c in cands] == ["v1"]     # v2 below score, v3 bad
    assert cands[0].media_type == "video"
    assert cands[0].score == 120000
    assert cands[0].author == "a"


def test_scrape_failure_is_swallowed():
    def boom(url, n):
        raise RuntimeError("tiktok changed its site")
    src = TikTokSource(_config(enabled=True), lister=boom)
    feed = Feed(source="tiktok", name="t", tags=["landscaping"],
                target_accounts=["acct_main"])
    assert list(src.fetch(feed)) == []     # degrades, does not raise


def test_pipeline_isolates_disabled_tiktok(tmp_path, monkeypatch):
    """A disabled (or broken) tiktok feed must not stop other feeds running."""
    from igbot import pipeline
    from igbot.db import Store
    from igbot.media.downloader import MediaInfo
    from igbot.models import Candidate

    cfg = Config(
        mode="review", max_posts_per_run=20, work_dir=tmp_path,
        db_path=tmp_path / "t.db", reddit_user_agent="ua",
        feeds=[Feed(source="tiktok", name="tt", tags=["x"],
                    target_accounts=["acct_main"]),
               Feed(source="reddit", name="rr", subreddits=["s"],
                    target_accounts=["acct_main"])],
        accounts=[__import__("igbot.config", fromlist=["Account"]).Account(
            id="acct_main", username="m")],
        host=None, instagram=None, brand=None, x=XConfig(),
        tiktok=TikTokConfig(enabled=False),
    )

    class _Reddit:
        name = "reddit"
        def __init__(self, c): pass
        def fetch(self, feed):
            yield Candidate(source="reddit", source_post_id="p1",
                            media_type="video", source_url="u",
                            target_accounts=["acct_main"])

    monkeypatch.setattr(pipeline, "RedditSource", _Reddit)
    monkeypatch.setattr(pipeline, "download_and_normalize",
                        lambda *a, **k: MediaInfo(tmp_path / "v.mp4", "video",
                                                  10.0, 1080, 1920, True, True))
    ids = pipeline.run_fetch(cfg)         # tiktok disabled -> skipped, reddit runs
    assert len(ids) == 1
    s = Store(cfg.db_path)
    assert s.is_seen("reddit", "p1") is True
    s.close()
