"""Tests for the Instagram publisher — the 3-step container dance, the queried
publishing limit, Reels-vs-feed selection, and usage-header backoff.

No network: a fake session returns queued, recorded responses.
"""

from __future__ import annotations

import json

import pytest

from igbot.publish.instagram import (
    InstagramPublisher,
    PublishError,
    RateLimitError,
)


class FakeResp:
    def __init__(self, body, status=200, headers=None):
        self._body = body
        self.status_code = status
        self.headers = headers or {}
        self.text = json.dumps(body)

    def json(self):
        return self._body


class FakeSession:
    """Returns queued responses; records each request for assertions."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def request(self, method, url, params=None, timeout=None):
        self.calls.append((method, url, params or {}))
        return self._responses.pop(0)


def _pub(session, **kw):
    return InstagramPublisher("ig123", "tok", session=session, **kw)


LIMIT_OK = FakeResp({"data": [{"config": {"quota_total": 50}, "quota_usage": 3}]})


def test_publish_image_happy_path():
    session = FakeSession([
        LIMIT_OK,                                   # content_publishing_limit
        FakeResp({"id": "cont_1"}),                 # create container
        FakeResp({"id": "media_99"}),               # media_publish
    ])
    pub = _pub(session)
    media_id = pub.publish("https://cdn/x.jpg", "image", "caption here")
    assert media_id == "media_99"

    # container creation used image_url, not video_url
    _, url, params = session.calls[1]
    assert url.endswith("/ig123/media")
    assert params["image_url"] == "https://cdn/x.jpg"
    assert "video_url" not in params
    # publish used the creation_id
    assert session.calls[2][2]["creation_id"] == "cont_1"


def test_publish_video_polls_until_finished():
    session = FakeSession([
        LIMIT_OK,
        FakeResp({"id": "cont_v"}),                 # create
        FakeResp({"status_code": "IN_PROGRESS"}),   # poll 1
        FakeResp({"status_code": "FINISHED"}),      # poll 2
        FakeResp({"id": "media_v"}),                # publish
    ])
    pub = _pub(session)
    media_id = pub.publish(
        "https://cdn/x.mp4", "video", "cap", poll_interval=0
    )
    assert media_id == "media_v"
    # Reels-eligible video -> media_type REELS
    assert session.calls[1][2]["media_type"] == "REELS"


def test_non_reel_video_publishes_as_feed_video():
    session = FakeSession([
        LIMIT_OK,
        FakeResp({"id": "cont_v"}),
        FakeResp({"status_code": "FINISHED"}),
        FakeResp({"id": "media_v"}),
    ])
    pub = _pub(session)
    pub.publish("https://cdn/x.mp4", "video", "cap", as_reel=False, poll_interval=0)
    assert session.calls[1][2]["media_type"] == "VIDEO"


def test_container_error_raises():
    session = FakeSession([
        LIMIT_OK,
        FakeResp({"id": "cont_v"}),
        FakeResp({"status_code": "ERROR", "status": "transcode failed"}),
    ])
    pub = _pub(session)
    with pytest.raises(PublishError):
        pub.publish("https://cdn/x.mp4", "video", poll_interval=0)


def test_refuses_when_limit_exhausted():
    session = FakeSession([
        FakeResp({"data": [{"config": {"quota_total": 25}, "quota_usage": 25}]}),
    ])
    pub = _pub(session)
    with pytest.raises(RateLimitError):
        pub.publish("https://cdn/x.jpg", "image")


def test_limit_is_queried_not_hardcoded():
    session = FakeSession([
        FakeResp({"data": [{"config": {"quota_total": 100}, "quota_usage": 40}]}),
    ])
    limit = _pub(session).publishing_limit()
    assert limit.quota_total == 100 and limit.remaining == 60


def test_unknown_ceiling_does_not_block_publish():
    # Endpoint omits config/quota_total -> unknown ceiling, must NOT refuse.
    session = FakeSession([
        FakeResp({"data": [{"quota_usage": 7}]}),   # no config block
        FakeResp({"id": "c"}),
        FakeResp({"id": "m"}),
    ])
    media_id = _pub(session).publish("https://cdn/x.jpg", "image")
    assert media_id == "m"


def test_empty_app_usage_header_is_safe(monkeypatch):
    # Meta sends X-App-Usage: {} at zero usage; must not raise or back off.
    slept = []
    monkeypatch.setattr("igbot.publish.instagram.time.sleep", lambda s: slept.append(s))
    session = FakeSession([
        FakeResp({"data": [{"config": {"quota_total": 50}, "quota_usage": 1}]},
                 headers={"X-App-Usage": "{}"}),
        FakeResp({"id": "c"}),
        FakeResp({"id": "m"}),
    ])
    _pub(session).publish("https://cdn/x.jpg", "image")
    assert slept == []


def test_usage_header_backoff(monkeypatch):
    slept = []
    monkeypatch.setattr("igbot.publish.instagram.time.sleep", lambda s: slept.append(s))
    session = FakeSession([
        FakeResp({"data": [{"config": {"quota_total": 50}, "quota_usage": 1}]},
                 headers={"X-App-Usage": json.dumps({"call_count": 95})}),
        FakeResp({"id": "c"}),
        FakeResp({"id": "m"}),
    ])
    _pub(session).publish("https://cdn/x.jpg", "image")
    assert slept and slept[0] > 0   # backed off because usage hit 95%
