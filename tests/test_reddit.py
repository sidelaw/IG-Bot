"""Reddit source: public RSS (top.rss) parsing — no API key, no network."""

from __future__ import annotations

from types import SimpleNamespace

from igbot.config import Feed
from igbot.sources.reddit import RedditSource

# A trimmed Atom feed like reddit.com/r/sub/top.rss returns. The <content> HTML
# is entity-escaped exactly as reddit serves it.
_FEED = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <author><name>/u/greenthumb</name></author>
    <content type="html">&lt;a href="https://i.redd.it/abc123.jpg"&gt;&lt;img/&gt;&lt;/a&gt; submitted by &lt;a href="https://www.reddit.com/user/greenthumb"&gt;/u/greenthumb&lt;/a&gt;</content>
    <id>t3_img1</id>
    <link href="https://www.reddit.com/r/lawncare/comments/img1/nice_lawn/"/>
    <title>Nice lawn</title>
  </entry>
  <entry>
    <author><name>/u/mower</name></author>
    <content type="html">&lt;span&gt;&lt;a href="https://v.redd.it/xyz789"&gt;[link]&lt;/a&gt;&lt;/span&gt;</content>
    <id>t3_vid1</id>
    <link href="https://www.reddit.com/r/lawncare/comments/vid1/mowing/"/>
    <title>Mowing stripes</title>
  </entry>
  <entry>
    <author><name>/u/talker</name></author>
    <content type="html">&lt;p&gt;Just a text post, no media&lt;/p&gt;</content>
    <id>t3_self1</id>
    <link href="https://www.reddit.com/r/lawncare/comments/self1/q/"/>
    <title>A question</title>
  </entry>
</feed>"""


class FakeSession:
    def __init__(self, content=_FEED, status=200):
        self.content = content
        self.status = status
        self.headers = {}
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params or {}))
        return SimpleNamespace(status_code=self.status, content=self.content)


def _source(session):
    cfg = SimpleNamespace(reddit_user_agent="igbot/test")
    return RedditSource(cfg, session=session)


def _feed(**kw):
    kw.setdefault("source", "reddit")
    kw.setdefault("name", "f")
    kw.setdefault("subreddits", ["lawncare"])
    kw.setdefault("target_accounts", ["acct_main"])
    return Feed(**kw)


def test_parses_image_and_video_skips_text():
    src = _source(FakeSession())
    cands = {c.source_post_id: c for c in src.fetch(_feed())}
    assert set(cands) == {"img1", "vid1"}      # self/text post skipped

    img = cands["img1"]
    assert img.media_type == "image"
    assert img.source_url == "https://i.redd.it/abc123.jpg"
    assert img.author == "greenthumb"
    assert img.title == "Nice lawn"
    assert img.permalink.endswith("/comments/img1/nice_lawn/")

    vid = cands["vid1"]
    assert vid.media_type == "video"
    # video downloads via the permalink (yt-dlp merges the v.redd.it audio)
    assert vid.source_url == "https://www.reddit.com/r/lawncare/comments/vid1/mowing/"


def test_media_type_filter_image_only():
    src = _source(FakeSession())
    got = {c.source_post_id for c in src.fetch(_feed(media_types=["image"]))}
    assert got == {"img1"}


def test_no_credentials_needed():
    # Construction must not require any Reddit env vars / keys.
    src = RedditSource(SimpleNamespace(reddit_user_agent=""))
    assert src.name == "reddit"


def test_rss_url_and_params():
    session = FakeSession()
    src = _source(session)
    list(src.fetch(_feed(subreddits=["gardening"], time_window="week")))
    url, params = session.calls[0]
    assert url == "https://www.reddit.com/r/gardening/top.rss"
    assert params["t"] == "week"
    assert 1 <= params["limit"] <= 100


def test_http_error_is_skipped_not_raised():
    src = _source(FakeSession(status=429))
    assert list(src.fetch(_feed())) == []
