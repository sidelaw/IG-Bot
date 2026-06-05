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


def test_video_logo_overlay_runs_and_scales(tmp_path):
    from PIL import Image

    src = tmp_path / "src.mp4"
    subprocess.run(
        ["ffmpeg", "-y",
         "-f", "lavfi", "-i", "testsrc=size=1080x1920:rate=30:duration=3",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
         "-shortest", str(src)],
        check=True, capture_output=True,
    )
    logo = tmp_path / "logo.png"
    Image.new("RGBA", (900, 900), (255, 0, 0, 255)).save(logo, "PNG")

    brand = BrandConfig(text="", logo_path=str(logo), position="bottom-right")
    out = overlay.apply_video_overlay(src, tmp_path / "out.mp4", brand)
    assert out.exists()
    assert dl.has_audio_stream(out) is True
    # output frame is still the source size (logo composited, not the canvas)
    info = dl.probe(out)
    w, h = dl._video_dims(info)
    assert (w, h) == (1080, 1920)


def test_video_text_overlay_with_space_in_path(tmp_path):
    # work_dir containing a space must not corrupt the drawtext filtergraph.
    work = tmp_path / "my work dir"
    work.mkdir()
    src = work / "src.mp4"
    subprocess.run(
        ["ffmpeg", "-y",
         "-f", "lavfi", "-i", "testsrc=size=720x1280:rate=30:duration=2",
         str(src)],
        check=True, capture_output=True,
    )
    brand = BrandConfig(text="@landscaper")
    out = overlay.apply_video_overlay(src, work / "out.mp4", brand)
    assert out.exists()


def test_esc_filter():
    assert overlay._esc_filter("/a/b.ttf") == "/a/b.ttf"
    assert overlay._esc_filter("/a:b/c'd") == "/a\\:b/c\\'d"


def test_overlay_dispatch_and_no_brand(tmp_path):
    assert overlay.has_overlay(BrandConfig(text="x")) is True
    assert overlay.has_overlay(BrandConfig()) is False
