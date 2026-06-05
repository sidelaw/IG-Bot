"""Download + normalize media.

The Reddit audio fix lives here: ``v.redd.it`` stores video and audio as
*separate* streams, so requesting only the video gives a silent clip. We let
``yt-dlp`` select ``bv*+ba/b`` (best video + best audio, falling back to a
combined stream) and merge with ``ffmpeg`` — yt-dlp locates the audio stream
and muxes it automatically. We do NOT hand-roll a stream fetcher.

Video is then normalized to MP4 / H.264 / AAC with the ``moov`` atom moved to
the front (``+faststart``). Images are converted to JPEG (Instagram rejects
PNG). Reels eligibility (5-90 s, 9:16) is computed and surfaced, never enforced.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

# Reels reach window. Outside this (or non-9:16) a clip still publishes, but as
# a regular feed video rather than a Reel. We surface this; we don't block it.
REELS_MIN_SEC = 5.0
REELS_MAX_SEC = 90.0
REELS_ASPECT = 9 / 16  # width / height
_ASPECT_TOLERANCE = 0.02


class MediaError(RuntimeError):
    pass


@dataclass
class MediaInfo:
    path: Path
    media_type: str          # "video" | "image"
    duration: float | None
    width: int | None
    height: int | None
    has_audio: bool
    reels_eligible: bool


def _require(tool: str) -> str:
    found = shutil.which(tool)
    if not found:
        raise MediaError(f"`{tool}` not found on PATH. Install ffmpeg (ffmpeg+ffprobe).")
    return found


def probe(path: str | Path) -> dict:
    """Return ffprobe JSON for a media file."""
    ffprobe = _require("ffprobe")
    out = subprocess.run(
        [ffprobe, "-v", "error", "-show_format", "-show_streams",
         "-of", "json", str(path)],
        capture_output=True, text=True,
    )
    if out.returncode != 0:
        raise MediaError(f"ffprobe failed for {path}: {out.stderr.strip()}")
    return json.loads(out.stdout or "{}")


def has_audio_stream(path: str | Path) -> bool:
    """True if the file contains at least one audio stream (the audio-fix check)."""
    for stream in probe(path).get("streams", []):
        if stream.get("codec_type") == "audio":
            return True
    return False


def _video_dims(info: dict) -> tuple[int | None, int | None]:
    for stream in info.get("streams", []):
        if stream.get("codec_type") == "video":
            return stream.get("width"), stream.get("height")
    return None, None


def _is_reels_eligible(duration: float | None, w: int | None, h: int | None) -> bool:
    if duration is None or w is None or h is None or h == 0:
        return False
    if not (REELS_MIN_SEC <= duration <= REELS_MAX_SEC):
        return False
    return abs((w / h) - REELS_ASPECT) <= _ASPECT_TOLERANCE


def _download_raw(url: str, dest_dir: Path) -> Path:
    """Download via yt-dlp with audio muxed. Returns the merged file path."""
    from yt_dlp import YoutubeDL

    _require("ffmpeg")  # yt-dlp needs it to merge the separate streams
    dest_dir.mkdir(parents=True, exist_ok=True)
    opts = {
        # THE AUDIO FIX: best video + best audio, fallback to best combined.
        "format": "bv*+ba/b",
        "merge_output_format": "mp4",
        "outtmpl": str(dest_dir / "%(id)s.%(ext)s"),
        "quiet": True,
        "noprogress": True,
        "noplaylist": True,
    }
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        path = Path(ydl.prepare_filename(info))
    # After a merge the container is mp4 regardless of the pre-merge ext.
    if not path.exists():
        merged = path.with_suffix(".mp4")
        if merged.exists():
            path = merged
    if not path.exists():
        raise MediaError(f"yt-dlp produced no file for {url}")
    return path


def _normalize_video(src: Path, dest_dir: Path, post_id: str) -> MediaInfo:
    ffmpeg = _require("ffmpeg")
    out = dest_dir / f"{post_id}.mp4"
    keep_audio = has_audio_stream(src)
    cmd = [
        ffmpeg, "-y", "-i", str(src),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",  # moov atom at front
    ]
    cmd += (["-c:a", "aac", "-b:a", "128k"] if keep_audio else ["-an"])
    cmd.append(str(out))
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise MediaError(f"ffmpeg normalize failed: {res.stderr.strip()[-500:]}")

    info = probe(out)
    # Distinguish "missing" from a real (possibly tiny) duration; `or None`
    # would silently drop a legitimate 0.x-second clip.
    dur_raw = info.get("format", {}).get("duration")
    try:
        duration = float(dur_raw) if dur_raw not in (None, "", "N/A") else None
    except (TypeError, ValueError):
        duration = None
    w, h = _video_dims(info)
    return MediaInfo(
        path=out,
        media_type="video",
        duration=duration,
        width=w,
        height=h,
        has_audio=has_audio_stream(out),
        reels_eligible=_is_reels_eligible(duration, w, h),
    )


def _normalize_image(src: Path, dest_dir: Path, post_id: str) -> MediaInfo:
    from PIL import Image

    out = dest_dir / f"{post_id}.jpg"
    with Image.open(src) as im:
        rgb = im.convert("RGB")  # drops alpha; JPEG only (IG rejects PNG)
        rgb.save(out, "JPEG", quality=90)
        w, h = rgb.size
    return MediaInfo(
        path=out, media_type="image", duration=None,
        width=w, height=h, has_audio=False, reels_eligible=False,
    )


def download_and_normalize(
    url: str, media_type: str, work_dir: str | Path, post_id: str
) -> MediaInfo:
    """Download ``url`` and normalize to an IG-ready file.

    ``media_type`` is "video" or "image". Returns a :class:`MediaInfo` with the
    normalized path plus probed metadata (duration, dims, audio, reels).
    """
    work_dir = Path(work_dir)
    raw_dir = work_dir / "raw"
    out_dir = work_dir / "normalized"
    out_dir.mkdir(parents=True, exist_ok=True)

    if media_type == "video":
        raw = _download_raw(url, raw_dir)
        return _normalize_video(raw, out_dir, post_id)
    elif media_type == "image":
        raw = _download_url(url, raw_dir, post_id)
        return _normalize_image(raw, out_dir, post_id)
    raise MediaError(f"unsupported media_type: {media_type!r}")


def _download_url(url: str, dest_dir: Path, post_id: str) -> Path:
    """Plain HTTP download (images)."""
    import requests

    dest_dir.mkdir(parents=True, exist_ok=True)
    raw = dest_dir / f"{post_id}.bin"
    with requests.get(url, stream=True, timeout=30) as r:
        r.raise_for_status()
        with raw.open("wb") as fh:
            for chunk in r.iter_content(chunk_size=1 << 16):
                fh.write(chunk)
    return raw
