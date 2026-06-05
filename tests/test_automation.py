"""Scheduled automation: harvest queues top posts; post_next publishes them."""

from __future__ import annotations

from pathlib import Path

import pytest

from igbot.automation import runner
from igbot.config import (
    Account,
    AutomationConfig,
    BrandConfig,
    Config,
    Feed,
    HostConfig,
    InstagramConfig,
    TikTokConfig,
    XConfig,
)
from igbot.media.downloader import MediaInfo
from igbot.models import Candidate
from igbot.publish.instagram import PublishError, RateLimitError


class FakeHost:
    """In-memory stand-in for the R2 host (upload + JSON state)."""

    def __init__(self):
        self.state: dict = {}
        self.uploaded: list[str] = []

    def upload(self, path):
        self.uploaded.append(str(path))
        return f"https://cdn/{Path(path).name}"

    def get_json(self, name, default=None):
        return self.state.get(name, default)

    def put_json(self, name, obj):
        self.state[name] = obj


class FakeSource:
    name = "reddit"

    def __init__(self, config):
        pass

    def fetch(self, feed):
        sub = feed.subreddits[0]
        for i in range(3):
            yield Candidate(
                source="reddit", source_post_id=f"{sub}_{i}",
                media_type="video", source_url="u", title=f"top {i}",
                permalink=f"https://reddit.com/{sub}/{i}", author="someone",
                target_accounts=list(feed.target_accounts),
            )


def _config(tmp_path, **automation) -> Config:
    return Config(
        mode="blind", max_posts_per_run=20,
        work_dir=tmp_path, db_path=tmp_path / "t.db", reddit_user_agent="ua",
        feeds=[
            Feed(source="reddit", name="a", subreddits=["lawncare"],
                 target_accounts=["acct_main"]),
            Feed(source="reddit", name="b", subreddits=["gardening"],
                 target_accounts=["acct_two"]),
        ],
        accounts=[Account(id="acct_main"), Account(id="acct_two")],
        host=HostConfig(bucket="b", public_base_url="https://cdn"),
        instagram=InstagramConfig(), brand=BrandConfig(), x=XConfig(),
        tiktok=TikTokConfig(),
        automation=AutomationConfig(**{"harvest_count": 2, **automation}),
    )


@pytest.fixture
def patched(monkeypatch, tmp_path):
    monkeypatch.setattr(
        runner, "download_and_normalize",
        lambda url, mt, work, pid: MediaInfo(tmp_path / f"{pid}.mp4", "video",
                                             10.0, 1080, 1920, True, True),
    )


def test_harvest_queues_top_n_routed_per_subreddit(patched, tmp_path):
    cfg = _config(tmp_path)
    host = FakeHost()
    added = runner.harvest(cfg, host=host, source_factory=FakeSource)

    # 2 feeds x harvest_count 2 = 4 unique posts queued
    assert len(added) == 4
    queue = host.state["queue.json"]
    assert len(queue) == 4
    # routing: lawncare -> acct_main, gardening -> acct_two
    routes = {(e["post_id"], e["account_id"]) for e in queue}
    assert ("lawncare_0", "acct_main") in routes
    assert ("gardening_0", "acct_two") in routes
    assert all(e["public_url"].startswith("https://cdn/") for e in queue)


def test_harvest_dedups_against_seen(patched, tmp_path):
    cfg = _config(tmp_path, harvest_count=5)   # consume all 3 per feed in run 1
    host = FakeHost()
    runner.harvest(cfg, host=host, source_factory=FakeSource)
    first = len(host.state["queue.json"])
    # second run: everything already seen -> nothing new queued
    added2 = runner.harvest(cfg, host=host, source_factory=FakeSource)
    assert added2 == []
    assert len(host.state["queue.json"]) == first


def test_caption_suffix_applied(patched, tmp_path):
    cfg = _config(tmp_path, caption_suffix="#lawn")
    host = FakeHost()
    runner.harvest(cfg, host=host, source_factory=FakeSource)
    assert all(e["caption"].endswith("#lawn") for e in host.state["queue.json"])


class _FakePublisher:
    def __init__(self, *a, **k):
        self.published = None

    def publish(self, url, media_type, caption="", *, as_reel=True):
        self.published = (url, media_type, caption, as_reel)
        return "media_1"


def _seed_queue(host, *entries):
    host.state["queue.json"] = list(entries)


def _entry(post_id="p1", account="acct_main"):
    return {"post_id": post_id, "account_id": account, "media_type": "video",
            "public_url": "https://cdn/p1.mp4", "caption": "hi", "as_reel": True}


def test_post_next_publishes_oldest_and_dequeues(monkeypatch, tmp_path):
    cfg = _config(tmp_path)
    host = FakeHost()
    _seed_queue(host, _entry("p1"), _entry("p2"))
    monkeypatch.setenv("IGBOT_TOKEN_ACCT_MAIN", "tok")
    monkeypatch.setenv("IGBOT_IGID_ACCT_MAIN", "ig1")

    media_id = runner.post_next(cfg, host=host,
                                publisher_factory=lambda i, t: _FakePublisher())
    assert media_id == "media_1"
    # oldest removed, one left
    assert [e["post_id"] for e in host.state["queue.json"]] == ["p2"]


def test_post_next_empty_queue(tmp_path):
    cfg = _config(tmp_path)
    host = FakeHost()
    assert runner.post_next(cfg, host=host) is None


def test_post_next_missing_creds_drops_item(monkeypatch, tmp_path):
    cfg = _config(tmp_path)
    host = FakeHost()
    _seed_queue(host, _entry("p1"))
    monkeypatch.delenv("IGBOT_TOKEN_ACCT_MAIN", raising=False)
    assert runner.post_next(cfg, host=host) is None
    assert host.state["queue.json"] == []        # dropped so it can't block


def test_post_next_rate_limited_keeps_item(monkeypatch, tmp_path):
    cfg = _config(tmp_path)
    host = FakeHost()
    _seed_queue(host, _entry("p1"))
    monkeypatch.setenv("IGBOT_TOKEN_ACCT_MAIN", "tok")
    monkeypatch.setenv("IGBOT_IGID_ACCT_MAIN", "ig1")

    class _RL:
        def publish(self, *a, **k):
            raise RateLimitError("daily cap reached")

    assert runner.post_next(cfg, host=host, publisher_factory=lambda i, t: _RL()) is None
    assert len(host.state["queue.json"]) == 1     # left for next run


def test_post_next_bad_media_dropped(monkeypatch, tmp_path):
    cfg = _config(tmp_path)
    host = FakeHost()
    _seed_queue(host, _entry("p1"), _entry("p2"))
    monkeypatch.setenv("IGBOT_TOKEN_ACCT_MAIN", "tok")
    monkeypatch.setenv("IGBOT_IGID_ACCT_MAIN", "ig1")

    class _Bad:
        def publish(self, *a, **k):
            raise PublishError("unsupported media")

    assert runner.post_next(cfg, host=host, publisher_factory=lambda i, t: _Bad()) is None
    assert [e["post_id"] for e in host.state["queue.json"]] == ["p2"]   # bad one dropped
