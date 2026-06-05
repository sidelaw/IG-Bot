"""SQLite-backed state: dedup, candidate/review queue, routing, publish log.

The DB file holds tokens and third-party metadata and is gitignored.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from ..models import Candidate

_SCHEMA = Path(__file__).with_name("schema.sql")


class Store:
    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self._init_schema()

    def _init_schema(self) -> None:
        self.conn.executescript(_SCHEMA.read_text())
        self.conn.commit()

    # ----- dedup -----

    def is_seen(self, source: str, source_post_id: str) -> bool:
        cur = self.conn.execute(
            "SELECT 1 FROM seen_posts WHERE source = ? AND source_post_id = ?",
            (source, source_post_id),
        )
        return cur.fetchone() is not None

    def mark_seen(
        self, source: str, source_post_id: str, content_hash: str | None = None
    ) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO seen_posts (source, source_post_id, content_hash) "
            "VALUES (?, ?, ?)",
            (source, source_post_id, content_hash),
        )
        self.conn.commit()

    # ----- accounts -----

    def upsert_account(
        self, account_id: str, username: str = "", auth_flow: str = "instagram_login"
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO accounts (id, username, auth_flow) VALUES (?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET username = excluded.username,
                                          auth_flow = excluded.auth_flow
            """,
            (account_id, username, auth_flow),
        )
        self.conn.commit()

    # ----- candidates / review queue -----

    def add_candidate(self, c: Candidate) -> int:
        cur = self.conn.execute(
            """
            INSERT OR IGNORE INTO candidates
                (source, source_post_id, author, source_url, permalink, title,
                 media_type, score, local_path, duration, width, height,
                 has_audio, reels_eligible, caption, brand_overlay)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                c.source, c.source_post_id, c.author, c.source_url, c.permalink,
                c.title, c.media_type, c.score,
                str(c.local_path) if c.local_path else None,
                c.duration, c.width, c.height,
                _b(c.has_audio), _b(c.reels_eligible),
                c.caption, int(c.brand_overlay),
            ),
        )
        self.conn.commit()
        # rowcount==1 means the row was actually inserted; on OR IGNORE skips it is
        # 0, and lastrowid would be stale (pointing at some earlier insert).
        if cur.rowcount == 1:
            cand_id = cur.lastrowid
        else:  # already existed — look up the real id
            row = self.conn.execute(
                "SELECT id FROM candidates WHERE source = ? AND source_post_id = ?",
                (c.source, c.source_post_id),
            ).fetchone()
            cand_id = row["id"]
        for acct in c.target_accounts:
            self.add_routing(cand_id, acct)
        return cand_id

    def add_routing(self, candidate_id: int, account_id: str) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO routing (candidate_id, account_id) VALUES (?, ?)",
            (candidate_id, account_id),
        )
        self.conn.commit()

    def pending(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM candidates WHERE status = 'pending' ORDER BY score DESC"
        ).fetchall()

    def get_candidate(self, candidate_id: int) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM candidates WHERE id = ?", (candidate_id,)
        ).fetchone()

    def set_status(self, candidate_id: int, status: str) -> None:
        self.conn.execute(
            "UPDATE candidates SET status = ? WHERE id = ?", (status, candidate_id)
        )
        self.conn.commit()

    # ----- publish log -----

    def log_publish(
        self, candidate_id: int, account_id: str, status: str,
        ig_media_id: str | None = None, detail: str = "",
    ) -> None:
        self.conn.execute(
            "INSERT INTO publish_log (candidate_id, account_id, ig_media_id, "
            "status, detail) VALUES (?, ?, ?, ?, ?)",
            (candidate_id, account_id, ig_media_id, status, detail),
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()


def _b(v: bool | None) -> int | None:
    return None if v is None else int(v)
