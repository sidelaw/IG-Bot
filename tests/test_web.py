"""Review-queue web app: render, edit, route, approve."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from igbot.config import (
    Account,
    BrandConfig,
    Config,
    HostConfig,
    InstagramConfig,
    TikTokConfig,
    XConfig,
)
from igbot.db import Store
from igbot.models import Candidate
from igbot.web import create_app


def _config(tmp_path) -> Config:
    return Config(
        mode="review", max_posts_per_run=20,
        work_dir=tmp_path, db_path=tmp_path / "t.db",
        reddit_user_agent="ua", feeds=[],
        accounts=[Account(id="acct_main", username="main"),
                  Account(id="acct_two", username="two")],
        host=HostConfig(bucket="b", public_base_url="https://cdn"),
        instagram=InstagramConfig(), brand=BrandConfig(text="@x"), x=XConfig(), tiktok=TikTokConfig(),
    )


@pytest.fixture
def client(tmp_path):
    cfg = _config(tmp_path)
    img = tmp_path / "p1.jpg"
    Image.new("RGB", (100, 100), (1, 2, 3)).save(img, "JPEG")

    s = Store(cfg.db_path)
    s.upsert_account("acct_main", "main")
    s.upsert_account("acct_two", "two")
    s.add_candidate(Candidate(
        source="reddit", source_post_id="p1", media_type="image",
        source_url="u", permalink="https://reddit.com/p1", author="someone",
        title="before/after", score=300, local_path=img,
    ))
    s.close()
    return TestClient(create_app(cfg)), cfg


def test_index_lists_pending(client):
    c, _ = client
    r = c.get("/")
    assert r.status_code == 200
    assert "#1" in r.text and "before/after" in r.text
    assert "acct_main" in r.text and "acct_two" in r.text


def test_media_served(client):
    c, _ = client
    r = c.get("/media/1")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/")


def test_update_persists_caption_brand_routing(client):
    c, cfg = client
    r = c.post("/candidates/1/update",
               data={"caption": "Fresh sod install",
                     "brand_overlay": "1",
                     "accounts": ["acct_main", "acct_two"]},
               follow_redirects=False)
    assert r.status_code == 303
    s = Store(cfg.db_path)
    row = s.get_candidate(1)
    assert row["caption"] == "Fresh sod install"
    assert row["brand_overlay"] == 1
    assert set(s.routing_for(1)) == {"acct_main", "acct_two"}
    s.close()


def test_update_rejects_unknown_account(client):
    c, cfg = client
    r = c.post("/candidates/1/update",
               data={"caption": "x", "accounts": ["ghost"]},
               follow_redirects=False)
    assert r.status_code == 303
    assert "unknown" in r.headers["location"]
    s = Store(cfg.db_path)
    assert s.routing_for(1) == []      # nothing routed to a bogus account
    s.close()


def test_routing_can_be_replaced_and_cleared(client):
    c, cfg = client
    c.post("/candidates/1/update", data={"accounts": ["acct_main", "acct_two"]})
    c.post("/candidates/1/update", data={"accounts": ["acct_two"]})
    s = Store(cfg.db_path)
    assert s.routing_for(1) == ["acct_two"]
    c2 = TestClient(create_app(cfg))
    c2.post("/candidates/1/update", data={"caption": "no accounts"})
    assert s.routing_for(1) == []      # empty selection clears routing
    s.close()


def test_approve_and_reject(client):
    c, cfg = client
    c.post("/candidates/1/approve")
    s = Store(cfg.db_path)
    assert s.get_candidate(1)["status"] == "approved"
    c.post("/candidates/1/reject")
    assert s.get_candidate(1)["status"] == "rejected"
    s.close()
