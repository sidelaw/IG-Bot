"""Configuration loading.

Non-secret settings come from a TOML file (read with stdlib ``tomllib``).
Secrets (API keys, tokens) come from environment variables only — never the
TOML file, never the repo. See ``.env.example``.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import TypeVar

_T = TypeVar("_T")


def _build(cls: type[_T], data: dict, where: str) -> _T:
    """Construct a dataclass from a TOML table, rejecting unknown keys clearly.

    A bare ``cls(**data)`` raises a cryptic stdlib TypeError on any typo'd key
    (e.g. ``timewindow`` for ``time_window``). This names the offending key and
    where it lives so the operator can fix config.toml.
    """
    allowed = {f.name for f in fields(cls)}
    unknown = set(data) - allowed
    if unknown:
        raise ValueError(
            f"unknown key(s) {sorted(unknown)} in [{where}]; "
            f"valid keys: {sorted(allowed)}"
        )
    try:
        return cls(**data)
    except TypeError as exc:  # missing required field
        raise ValueError(f"invalid [{where}] config: {exc}") from exc


@dataclass
class Feed:
    source: str
    name: str
    subreddits: list[str] = field(default_factory=list)   # reddit feeds
    queries: list[str] = field(default_factory=list)       # x feeds (search queries)
    time_window: str = "week"
    min_score: int = 0          # reddit: post score; x: likes + retweets
    media_types: list[str] = field(default_factory=lambda: ["video", "image"])
    target_accounts: list[str] = field(default_factory=list)


@dataclass
class Account:
    id: str
    username: str = ""
    auth_flow: str = "instagram_login"


@dataclass
class HostConfig:
    """Public media host (S3-compatible: AWS S3 or Cloudflare R2)."""
    provider: str = "s3"
    bucket: str = ""
    region: str = "auto"
    endpoint_url: str = ""        # set for R2; empty -> AWS default
    public_base_url: str = ""     # CDN / public domain that serves the bucket
    key_prefix: str = "igbot"


@dataclass
class InstagramConfig:
    # Instagram Login flow uses graph.instagram.com. Version is volatile (Meta
    # ships quarterly) — keep it here, not hardcoded in code.
    graph_host: str = "graph.instagram.com"
    api_version: str = "v23.0"


@dataclass
class XConfig:
    # X (Twitter) API v2. Pay-per-use since Feb 2026 (~$0.005/post read) — each
    # search run costs money. App-only Bearer auth; recent search = last 7 days.
    api_base: str = "https://api.x.com/2"
    # Appended to every feed query; ensures media-bearing originals only.
    query_suffix: str = "has:media -is:retweet -is:reply"
    max_results: int = 50       # 10..100 per search request


@dataclass
class BrandConfig:
    """Brand overlay (the 'material edit' transform for reach). Applied at
    publish time when a candidate has brand_overlay enabled."""
    text: str = ""                # overlay text (e.g. "@youraccount")
    logo_path: str = ""           # optional PNG/JPEG logo to composite
    position: str = "bottom-right"  # bottom-right|bottom-left|top-right|top-left|bottom-center
    font_size: int = 48           # px; scaled to media for video
    margin: int = 36              # px from the edge
    opacity: float = 0.85         # 0..1


@dataclass
class Config:
    mode: str
    max_posts_per_run: int
    work_dir: Path
    db_path: Path
    reddit_user_agent: str
    feeds: list[Feed]
    accounts: list[Account]
    host: HostConfig
    instagram: InstagramConfig
    brand: BrandConfig
    x: XConfig

    def account(self, account_id: str) -> Account | None:
        return next((a for a in self.accounts if a.id == account_id), None)

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

    @staticmethod
    def x_bearer_token() -> str:
        return os.environ.get("X_BEARER_TOKEN", "")


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

    feeds = [_build(Feed, f, f"feeds[{i}]") for i, f in enumerate(raw.get("feeds", []))]
    accounts = [_build(Account, a, f"accounts[{i}]")
                for i, a in enumerate(raw.get("accounts", []))]
    host = _build(HostConfig, raw.get("host", {}), "host")
    instagram = _build(InstagramConfig, raw.get("instagram", {}), "instagram")
    brand = _build(BrandConfig, raw.get("brand", {}), "brand")
    x = _build(XConfig, raw.get("x", {}), "x")

    return Config(
        mode=general.get("mode", "review"),
        max_posts_per_run=int(general.get("max_posts_per_run", 20)),
        work_dir=Path(paths.get("work_dir", "./work")),
        db_path=Path(paths.get("db_path", "./igbot.db")),
        reddit_user_agent=reddit.get("user_agent", "igbot/0.1"),
        feeds=feeds,
        accounts=accounts,
        host=host,
        instagram=instagram,
        brand=brand,
        x=x,
    )
