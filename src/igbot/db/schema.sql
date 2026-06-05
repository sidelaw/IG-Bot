-- IG-Bot state. The DB file holds tokens — it is gitignored. Never commit it.

-- Dedup: every post we've ever seen (by source id and/or content hash).
CREATE TABLE IF NOT EXISTS seen_posts (
    id             INTEGER PRIMARY KEY,
    source         TEXT NOT NULL,
    source_post_id TEXT NOT NULL,
    content_hash   TEXT,
    first_seen     TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (source, source_post_id)
);
CREATE INDEX IF NOT EXISTS idx_seen_hash ON seen_posts (content_hash);

-- Review queue: one row per fetched candidate.
CREATE TABLE IF NOT EXISTS candidates (
    id             INTEGER PRIMARY KEY,
    source         TEXT NOT NULL,
    source_post_id TEXT NOT NULL,
    author         TEXT,
    source_url     TEXT,           -- direct media url
    permalink      TEXT,           -- human-facing source link (attribution)
    title          TEXT,
    media_type     TEXT,           -- "video" | "image"
    score          INTEGER,
    local_path     TEXT,           -- normalized file on disk
    duration       REAL,           -- seconds (video)
    width          INTEGER,
    height         INTEGER,
    has_audio      INTEGER,        -- 0/1
    reels_eligible INTEGER,        -- 0/1 (5-90s & 9:16)
    caption        TEXT,           -- operator-editable
    brand_overlay  INTEGER DEFAULT 0,
    status         TEXT DEFAULT 'pending',  -- pending|approved|published|rejected
    created_at     TEXT DEFAULT (datetime('now')),
    UNIQUE (source, source_post_id)
);

-- Target Instagram accounts.
CREATE TABLE IF NOT EXISTS accounts (
    id         TEXT PRIMARY KEY,
    username   TEXT,
    auth_flow  TEXT,              -- instagram_login | facebook_login
    ig_user_id TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

-- Tokens kept out of config files entirely. Loaded from env at runtime; this
-- table is an optional runtime cache only. DB file is gitignored.
CREATE TABLE IF NOT EXISTS account_tokens (
    account_id   TEXT PRIMARY KEY REFERENCES accounts (id),
    access_token TEXT,
    expires_at   TEXT
);

-- Account routing: which candidate goes to which account(s).
CREATE TABLE IF NOT EXISTS routing (
    id           INTEGER PRIMARY KEY,
    candidate_id INTEGER NOT NULL REFERENCES candidates (id),
    account_id   TEXT NOT NULL REFERENCES accounts (id),
    UNIQUE (candidate_id, account_id)
);

-- Audit log of publish attempts.
CREATE TABLE IF NOT EXISTS publish_log (
    id           INTEGER PRIMARY KEY,
    candidate_id INTEGER,
    account_id   TEXT,
    ig_media_id  TEXT,
    status       TEXT,            -- created|published|error
    detail       TEXT,
    created_at   TEXT DEFAULT (datetime('now'))
);
