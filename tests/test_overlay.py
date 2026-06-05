"""Brand overlay: image (Pillow) and video (ffmpeg, audio preserved)."""

from __future__ import annotations

import shutil
import subprocess

import pytest

from igbot.config import BrandConfig
from igbot.media import downloader as dl
from igbot.media import overlay

pytestmark = pytest.mark.skipif(
    not (shutil.which("ffmpeg") and shutil.which("ffprobe")),
    reason="ffmpeg/ffprobe not installed",
)


def test_image_overlay_changes_pixels_and_stays_jpeg(tmp_path):
    from PIL import Image, ImageChops

    src = tmp_path / "src.jpg"
    Image.new("RGB", (800, 1000), (20, 110, 40)).save(src, "JPEG")

    brand = BrandConfig(text="@landscaper", position="bottom-right", font_size=60)
    out = overlay.apply_image_overlay(src, tmp_path / "out.jpg", brand)

    with Image.open(out) as im:
        assert im.format == "JPEG"
        assert im.size == (800, 1000)        # dimensions preserved
    # the overlay actually drew something
    diff = ImageChops.difference(
        Image.open(src).convert("RGB"), Image.open(out).convert("RGB")
    )
    assert diff.getbbox() is not None


def test_video_overlay_preserves_audio_and_faststart(tmp_path):
    src = tmp_path / "src.mp4"
    subprocess.run(
        ["ffmpeg", "-y",
         "-f", "lavfi", "-i", "testsrc=size=1080x1920:rate=30:duration=4",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=4",
         "-shortest", str(src)],
        check=True, capture_output=True,
    )
    assert dl.has_audio_stream(src) is True

    brand = BrandConfig(text="@landscaper", position="bottom-left")
    out = overlay.apply_video_overlay(src, tmp_path / "out.mp4", brand)

    assert out.exists()
    assert dl.has_audio_stream(out) is True       # audio survives the overlay
    assert b"moov" in out.read_bytes()[:4096]     # +faststart


def test_overlay_dispatch_and_no_brand(tmp_path):
    assert overlay.has_overlay(BrandConfig(text="x")) is True
    assert overlay.has_overlay(BrandConfig()) is False
