"""Tests for the download/normalize stage — especially the audio fix.

These build local fixtures with ffmpeg (no network), then assert that:
  - audio is detected and preserved through normalization,
  - silent video is handled without inventing audio,
  - images are converted to JPEG,
  - Reels eligibility (5-90s & 9:16) is computed correctly.
"""

from __future__ import annotations

import shutil
import subprocess

import pytest

from igbot.media import downloader as dl

pytestmark = pytest.mark.skipif(
    not (shutil.which("ffmpeg") and shutil.which("ffprobe")),
    reason="ffmpeg/ffprobe not installed",
)


def _make_video(path, seconds=6, w=1080, h=1920, with_audio=True):
    cmd = ["ffmpeg", "-y",
           "-f", "lavfi", "-i", f"testsrc=size={w}x{h}:rate=30:duration={seconds}"]
    if with_audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}"]
    cmd += ["-shortest", str(path)]
    subprocess.run(cmd, check=True, capture_output=True)


def test_audio_detected_and_preserved(tmp_path):
    src = tmp_path / "src.mp4"
    _make_video(src, seconds=6, w=1080, h=1920, with_audio=True)
    assert dl.has_audio_stream(src) is True

    info = dl._normalize_video(src, tmp_path, "post1")
    assert info.path.exists()
    assert info.has_audio is True          # the audio fix: audio survives
    assert info.media_type == "video"
    assert 5.0 <= (info.duration or 0) <= 7.0
    assert info.width == 1080 and info.height == 1920
    assert info.reels_eligible is True     # 6s, 9:16


def test_silent_video_has_no_audio(tmp_path):
    src = tmp_path / "silent.mp4"
    _make_video(src, seconds=6, with_audio=False)
    assert dl.has_audio_stream(src) is False

    info = dl._normalize_video(src, tmp_path, "post2")
    assert info.has_audio is False


def test_reels_eligibility_rules():
    # 9:16, in-window -> eligible
    assert dl._is_reels_eligible(30, 1080, 1920) is True
    # too long -> not eligible (publishes as feed video)
    assert dl._is_reels_eligible(120, 1080, 1920) is False
    # too short
    assert dl._is_reels_eligible(3, 1080, 1920) is False
    # wrong aspect (square)
    assert dl._is_reels_eligible(30, 1080, 1080) is False
    # missing data
    assert dl._is_reels_eligible(None, 1080, 1920) is False


def test_faststart_moov_at_front(tmp_path):
    src = tmp_path / "src.mp4"
    _make_video(src, seconds=5)
    info = dl._normalize_video(src, tmp_path, "post3")
    # With +faststart the moov atom precedes mdat near the file head.
    head = info.path.read_bytes()[:4096]
    assert b"moov" in head


def test_image_converted_to_jpeg(tmp_path):
    from PIL import Image

    png = tmp_path / "src.png"
    Image.new("RGBA", (640, 640), (10, 120, 40, 255)).save(png, "PNG")

    info = dl._normalize_image(png, tmp_path, "img1")
    assert info.path.suffix == ".jpg"
    with Image.open(info.path) as im:
        assert im.format == "JPEG"
        assert im.mode == "RGB"
    assert info.media_type == "image"
    assert info.has_audio is False
    assert info.reels_eligible is False
