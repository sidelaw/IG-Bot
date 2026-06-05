"""Tests for the SQLite store: dedup, candidate queue, account routing."""

from __future__ import annotations

from pathlib import Path

from igbot.db import Store
from igbot.models import Candidate


def _candidate() -> Candidate:
    return Candidate(
        source="reddit", source_post_id="abc1", media_type="video",
        source_url="https://www.reddit.com/r/x/comments/abc1/",
        author="someone", title="cool before/after", score=523,
        target_accounts=["acct_main", "acct_two"],
        local_path=Path("/tmp/abc1.mp4"), duration=42.0,
        width=1080, height=1920, has_audio=True, reels_eligible=True,
    )


def test_dedup(tmp_path):
    s = Store(tmp_path / "t.db")
    assert s.is_seen("reddit", "abc1") is False
    s.mark_seen("reddit", "abc1")
    assert s.is_seen("reddit", "abc1") is True
    s.close()


def test_candidate_and_routing(tmp_path):
    s = Store(tmp_path / "t.db")
    s.upsert_account("acct_main", "main")
    s.upsert_account("acct_two", "two")

    c = _candidate()
    cid = s.add_candidate(c)
    # idempotent: re-adding the same post returns the same id
    assert s.add_candidate(c) == cid

    pending = s.pending()
    assert len(pending) == 1
    assert pending[0]["score"] == 523
    assert pending[0]["has_audio"] == 1
    assert pending[0]["reels_eligible"] == 1

    n = s.conn.execute(
        "SELECT COUNT(*) c FROM routing WHERE candidate_id = ?", (cid,)
    ).fetchone()["c"]
    assert n == 2
    s.close()


def test_routing_requires_known_account(tmp_path):
    """Routing to an unsynced account should fail loudly (FK), not silently."""
    import sqlite3

    import pytest

    s = Store(tmp_path / "t.db")
    c = _candidate()  # references acct_main / acct_two, never upserted
    with pytest.raises(sqlite3.IntegrityError):
        s.add_candidate(c)
    s.close()
