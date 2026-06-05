"""Configuration loading.

Non-secret settings come from a TOML file (read with stdlib ``tomllib``).
Secrets (API keys, tokens) come from environment variables only — never the
TOML file, never the repo. See ``.env.example``.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Feed:
    source: str
    name: str
    subreddits: list[str] = field(default_factory=list)
    time_window: str = "week"
    min_score: int = 0
    media_types: list[str] = field(default_factory=lambda: ["video", "image"])
    target_accounts: list[str] = field(default_factory=list)


@dataclass
class Account:
    id: str
    username: str = ""
    auth_flow: str = "instagram_login"


@dataclass
class Config:
    mode: str
    max_posts_per_run: int
    work_dir: Path
    db_path: Path
    reddit_user_agent: str
    feeds: list[Feed]
    accounts: list[Account]

    # ----- secrets, pulled from env on demand (never stored in TOML) -----

    @staticmethod
    def reddit_credentials() -> dict[str, str]:
        return {
            "client_id": os.environ.get("REDDIT_CLIENT_ID", ""),
            "client_secret": os.environ.get("REDDIT_CLIENT_SECRET", ""),
            "username": os.environ.get("REDDIT_USERNAME", ""),
            "password": os.environ.get("REDDIT_PASSWORD", ""),
        }

    @staticmethod
    def ig_token(account_id: str) -> str:
        """Per-account IG token from env: IGBOT_TOKEN_<ACCOUNT_ID upper>."""
        key = f"IGBOT_TOKEN_{account_id.upper()}"
        return os.environ.get(key, "")


def load(path: str | Path = "config.toml") -> Config:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Copy config.example.toml to config.toml and edit."
        )
    with path.open("rb") as fh:
        raw = tomllib.load(fh)

    general = raw.get("general", {})
    paths = raw.get("paths", {})
    reddit = raw.get("reddit", {})

    feeds = [Feed(**f) for f in raw.get("feeds", [])]
    accounts = [Account(**a) for a in raw.get("accounts", [])]

    return Config(
        mode=general.get("mode", "review"),
        max_posts_per_run=int(general.get("max_posts_per_run", 20)),
        work_dir=Path(paths.get("work_dir", "./work")),
        db_path=Path(paths.get("db_path", "./igbot.db")),
        reddit_user_agent=reddit.get("user_agent", "igbot/0.1"),
        feeds=feeds,
        accounts=accounts,
    )
