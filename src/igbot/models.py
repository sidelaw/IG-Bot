"""Shared data structures passed between pipeline stages."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Candidate:
    """A single sourced post moving through the pipeline.

    Populated incrementally: a source produces the metadata fields; the
    downloader fills in the media fields (``local_path`` ... ``reels_eligible``).
    """

    source: str                 # "reddit" | "x" | "tiktok"
    source_post_id: str
    media_type: str             # "video" | "image"
    source_url: str             # direct media URL
    permalink: str = ""         # human-facing link, kept for attribution
    author: str = ""
    title: str = ""
    score: int = 0
    target_accounts: list[str] = field(default_factory=list)

    # Filled by the download + normalize stage.
    local_path: Path | None = None
    duration: float | None = None
    width: int | None = None
    height: int | None = None
    has_audio: bool | None = None
    reels_eligible: bool | None = None

    # Filled by the review stage.
    caption: str = ""
    brand_overlay: bool = False
