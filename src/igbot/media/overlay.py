"""Brand overlay — the 'material edit' transform.

IG suppresses reposts without material edits; a brand overlay (text handle
and/or logo) is one such edit. (It does NOT address copyright — see CLAUDE.md.)

Images go through Pillow, video through ffmpeg (audio preserved). Applied at
publish time when a candidate has ``brand_overlay`` enabled.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from ..config import BrandConfig
from .downloader import MediaError, has_audio_stream

_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
)


def _font_path() -> str | None:
    for p in _FONT_CANDIDATES:
        if Path(p).exists():
            return p
    return None


def has_overlay(brand: BrandConfig) -> bool:
    return bool(brand.text or brand.logo_path)


def _esc_filter(value: str) -> str:
    """Escape a path for use as an ffmpeg filtergraph option value.

    In a filtergraph ``:`` separates options and ``\\`` / ``'`` are meta, so a
    work_dir path containing any of them (or being passed unquoted with spaces)
    would corrupt the graph. Escape backslash first, then ``:`` and ``'``.
    """
    return value.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


# ----- ffmpeg position expressions -----

def _drawtext_xy(position: str, margin: int) -> tuple[str, str]:
    """x/y for drawtext (text box is tw x th; frame is w x h)."""
    m = margin
    return {
        "bottom-right": (f"w-tw-{m}", f"h-th-{m}"),
        "bottom-left": (f"{m}", f"h-th-{m}"),
        "top-right": (f"w-tw-{m}", f"{m}"),
        "top-left": (f"{m}", f"{m}"),
        "bottom-center": ("(w-tw)/2", f"h-th-{m}"),
    }.get(position, (f"w-tw-{m}", f"h-th-{m}"))


def _overlay_xy(position: str, margin: int) -> tuple[str, str]:
    """x/y for the overlay filter (logo is overlay_w x overlay_h)."""
    m = margin
    return {
        "bottom-right": (f"main_w-overlay_w-{m}", f"main_h-overlay_h-{m}"),
        "bottom-left": (f"{m}", f"main_h-overlay_h-{m}"),
        "top-right": (f"main_w-overlay_w-{m}", f"{m}"),
        "top-left": (f"{m}", f"{m}"),
        "bottom-center": ("(main_w-overlay_w)/2", f"main_h-overlay_h-{m}"),
    }.get(position, (f"main_w-overlay_w-{m}", f"main_h-overlay_h-{m}"))


def apply_video_overlay(src: Path, dest: Path, brand: BrandConfig) -> Path:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise MediaError("ffmpeg not found on PATH")
    alpha = max(0.0, min(brand.opacity, 1.0))
    keep_audio = has_audio_stream(src)

    inputs = ["-i", str(src)]
    last = "[0:v]"
    steps: list[str] = []
    tmp_text: Path | None = None

    if brand.logo_path:
        if not Path(brand.logo_path).exists():
            raise MediaError(f"logo not found: {brand.logo_path}")
        inputs += ["-i", brand.logo_path]
        lx, ly = _overlay_xy(brand.position, brand.margin)
        # Scale the logo to ~1/5 of the *video* width (preserving aspect) via
        # scale2ref — a plain scale=iw:ih would be a no-op and composite the
        # logo at full size. scale2ref emits [scaled_logo][video_passthrough].
        steps.append(
            f"[1:v]{last}scale2ref=w=main_w/5:h=main_w/5*ih/iw[lg][vid]"
        )
        steps.append(f"[lg]format=rgba,colorchannelmixer=aa={alpha}[lga]")
        steps.append(f"[vid][lga]overlay={lx}:{ly}[base]")
        last = "[base]"

    if brand.text:
        font = _font_path()
        if not font:
            raise MediaError("no TTF font available for drawtext overlay")
        fd, name = tempfile.mkstemp(suffix=".txt", dir=str(dest.parent))
        tmp_text = Path(name)
        tmp_text.write_text(brand.text)
        import os
        os.close(fd)
        tx, ty = _drawtext_xy(brand.position, brand.margin)
        # Escape the file paths for the filtergraph: ':' separates options,
        # '\' and "'" are meta. (brand.text itself is read from textfile, so it
        # needs no escaping here.)
        steps.append(
            f"{last}drawtext=textfile={_esc_filter(str(tmp_text))}:"
            f"fontfile={_esc_filter(font)}:"
            f"fontsize={brand.font_size}:fontcolor=white@{alpha}:"
            f"borderw=3:bordercolor=black@{alpha}:x={tx}:y={ty}[v]"
        )
        last = "[v]"

    if not steps:
        raise MediaError("brand overlay enabled but no text/logo configured")

    cmd = [ffmpeg, "-y", *inputs, "-filter_complex", ";".join(steps),
           "-map", last]
    if keep_audio:
        cmd += ["-map", "0:a", "-c:a", "copy"]
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(dest)]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True)
    finally:
        if tmp_text and tmp_text.exists():
            tmp_text.unlink()
    if res.returncode != 0:
        raise MediaError(f"ffmpeg overlay failed: {res.stderr.strip()[-500:]}")
    return dest


def apply_image_overlay(src: Path, dest: Path, brand: BrandConfig) -> Path:
    from PIL import Image, ImageDraw, ImageFont

    base = Image.open(src).convert("RGBA")
    w, h = base.size
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    a = int(max(0.0, min(brand.opacity, 1.0)) * 255)

    if brand.logo_path:
        if not Path(brand.logo_path).exists():
            raise MediaError(f"logo not found: {brand.logo_path}")
        logo = Image.open(brand.logo_path).convert("RGBA")
        target_w = max(1, w // 5)
        ratio = target_w / logo.width
        logo = logo.resize((target_w, max(1, int(logo.height * ratio))))
        if a < 255:
            alpha_band = logo.getchannel("A").point(lambda p: int(p * a / 255))
            logo.putalpha(alpha_band)
        lx, ly = _pil_xy(brand.position, w, h, logo.width, logo.height, brand.margin)
        layer.alpha_composite(logo, (lx, ly))

    if brand.text:
        font_path = _font_path()
        font = (ImageFont.truetype(font_path, brand.font_size)
                if font_path else ImageFont.load_default())
        bbox = draw.textbbox((0, 0), brand.text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        tx, ty = _pil_xy(brand.position, w, h, tw, th, brand.margin)
        # subtle stroke for legibility on any background
        draw.text((tx, ty), brand.text, font=font, fill=(255, 255, 255, a),
                  stroke_width=2, stroke_fill=(0, 0, 0, a))

    out = Image.alpha_composite(base, layer).convert("RGB")
    out.save(dest, "JPEG", quality=90)
    return dest


def _pil_xy(position, w, h, ow, oh, m) -> tuple[int, int]:
    return {
        "bottom-right": (w - ow - m, h - oh - m),
        "bottom-left": (m, h - oh - m),
        "top-right": (w - ow - m, m),
        "top-left": (m, m),
        "bottom-center": ((w - ow) // 2, h - oh - m),
    }.get(position, (w - ow - m, h - oh - m))


def apply_overlay(
    src: str | Path, media_type: str, brand: BrandConfig, work_dir: str | Path
) -> Path:
    """Render a branded copy of ``src``. Returns the new file path."""
    src = Path(src)
    out_dir = Path(work_dir) / "branded"
    out_dir.mkdir(parents=True, exist_ok=True)
    if media_type == "video":
        return apply_video_overlay(src, out_dir / f"{src.stem}_branded.mp4", brand)
    if media_type == "image":
        return apply_image_overlay(src, out_dir / f"{src.stem}_branded.jpg", brand)
    raise MediaError(f"unsupported media_type for overlay: {media_type!r}")
