"""X (Twitter) source: search parsing, media/variant extraction, scoring."""

from __future__ import annotations

import json

import pytest

from igbot.config import Config, Feed, XConfig


class FakeResp:
    def __init__(self, body, status=200):
        self._body = body
        self.status_code = status
        self.text = json.dumps(body)

    def json(self):
        return self._body


class FakeSession:
    def __init__(self, body):
        self.body = body
        self.headers = {}
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params or {}))
        return FakeResp(self.body)


def _payload():
    return {
        "data": [
            {"id": "1", "text": "lawn before/after", "author_id": "u1",
             "public_metrics": {"like_count": 400, "retweet_count": 150},
             "attachments": {"media_keys": ["vid1"]}},
            {"id": "2", "text": "fresh sod", "author_id": "u2",
             "public_metrics": {"like_count": 10, "retweet_count": 2},
             "attachments": {"media_keys": ["img2"]}},
            {"id": "3", "text": "gif", "author_id": "u1",
             "public_metrics": {"like_count": 900, "retweet_count": 100},
             "attachments": {"media_keys": ["gif3"]}},
            {"id": "4", "text": "no media here",
             "public_metrics": {"like_count": 5000, "retweet_count": 0}},
        ],
        "includes": {
            "users": [{"id": "u1", "username": "greenthumb"},
                      {"id": "u2", "username": "sodguy"}],
            "media": [
                {"media_key": "vid1", "type": "video", "url": None, "variants": [
                    {"bit_rate": 256000, "content_type": "video/mp4",
                     "url": "https://video.x/lo.mp4"},
                    {"bit_rate": 2176000, "content_type": "video/mp4",
                     "url": "https://video.x/hi.mp4"},
                    {"content_type": "application/x-mpegURL",
                     "url": "https://video.x/playlist.m3u8"},
                ]},
                {"media_key": "img2", "type": "photo",
                 "url": "https://pbs.x/img2.jpg"},
                {"media_key": "gif3", "type": "animated_gif", "url": None,
                 "variants": [{"bit_rate": 0, "content_type": "video/mp4",
                               "url": "https://video.x/gif3.mp4"}]},
            ],
        },
    }


def _config(monkeypatch):
    monkeypatch.setenv("X_BEARER_TOKEN", "tok")
    cfg = Config(
        mode="review", max_posts_per_run=20, work_dir=".", db_path="x.db",
        reddit_user_agent="ua", feeds=[], accounts=[],
        host=None, instagram=None, brand=None, x=XConfig(),
    )
    return cfg


def _source(monkeypatch, body):
    from igbot.sources.x import XSource
    return XSource(_config(monkeypatch), session=FakeSession(body))


def test_requires_bearer_token(monkeypatch):
    from igbot.sources.x import XSource
    monkeypatch.delenv("X_BEARER_TOKEN", raising=False)
    cfg = Config(mode="review", max_posts_per_run=20, work_dir=".", db_path="x.db",
                 reddit_user_agent="ua", feeds=[], accounts=[],
                 host=None, instagram=None, brand=None, x=XConfig())
    with pytest.raises(RuntimeError):
        XSource(cfg)


def test_video_picks_highest_bitrate_mp4(monkeypatch):
    src = _source(monkeypatch, _payload())
    feed = Feed(source="x", name="f", queries=["lawn"], min_score=0,
                target_accounts=["acct_main"])
    cands = {c.source_post_id: c for c in src.fetch(feed)}
    assert cands["1"].media_type == "video"
    assert cands["1"].source_url == "https://video.x/hi.mp4"   # highest bit_rate
    assert cands["1"].score == 550
    assert cands["1"].permalink == "https://x.com/greenthumb/status/1"
    assert cands["1"].author == "greenthumb"


def test_photo_requests_original(monkeypatch):
    src = _source(monkeypatch, _payload())
    feed = Feed(source="x", name="f", queries=["lawn"], min_score=0,
                target_accounts=["a"])
    cands = {c.source_post_id: c for c in src.fetch(feed)}
    assert cands["2"].media_type == "image"
    assert cands["2"].source_url == "https://pbs.x/img2.jpg?name=orig"


def test_animated_gif_is_video(monkeypatch):
    src = _source(monkeypatch, _payload())
    feed = Feed(source="x", name="f", queries=["lawn"], min_score=0,
                target_accounts=["a"])
    cands = {c.source_post_id: c for c in src.fetch(feed)}
    assert cands["3"].media_type == "video"
    assert cands["3"].source_url == "https://video.x/gif3.mp4"


def test_min_score_and_no_media_filtered(monkeypatch):
    src = _source(monkeypatch, _payload())
    feed = Feed(source="x", name="f", queries=["lawn"], min_score=500,
                target_accounts=["a"])
    got = {c.source_post_id for c in src.fetch(feed)}
    assert got == {"1", "3"}      # tweet 2 below score, tweet 4 has no media


def test_media_type_filter(monkeypatch):
    src = _source(monkeypatch, _payload())
    feed = Feed(source="x", name="f", queries=["lawn"], min_score=0,
                media_types=["image"], target_accounts=["a"])
    got = {c.source_post_id for c in src.fetch(feed)}
    assert got == {"2"}           # only the photo


def test_query_suffix_and_auth_applied(monkeypatch):
    session = FakeSession(_payload())
    from igbot.sources.x import XSource
    src = XSource(_config(monkeypatch), session=session)
    feed = Feed(source="x", name="f", queries=["lawn care"], target_accounts=["a"])
    list(src.fetch(feed))
    assert session.headers["Authorization"] == "Bearer tok"
    _, params = session.calls[0]
    assert "has:media -is:retweet" in params["query"]
    assert "(lawn care)" in params["query"]
    assert 10 <= params["max_results"] <= 100
