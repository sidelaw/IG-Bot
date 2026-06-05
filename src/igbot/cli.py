"""Command-line entry point.

    python -m igbot fetch [--config config.toml] [--limit N]
    python -m igbot probe <video-url>     # download one URL, report audio status
"""

from __future__ import annotations

import argparse
import logging
import sys

from . import config as config_mod
from .media import download_and_normalize


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )


def cmd_fetch(args: argparse.Namespace) -> int:
    from .pipeline import run_fetch

    cfg = config_mod.load(args.config)
    ids = run_fetch(cfg, limit=args.limit)
    print(f"\nQueued {len(ids)} candidate(s). Review with the queue (next milestone).")
    return 0


def cmd_probe(args: argparse.Namespace) -> int:
    """Download a single URL and report whether audio survived (audio-fix demo)."""
    info = download_and_normalize(
        args.url, args.type, args.work_dir, "probe_sample"
    )
    print(f"path:           {info.path}")
    print(f"type:           {info.media_type}")
    print(f"duration:       {info.duration}")
    print(f"dimensions:     {info.width}x{info.height}")
    print(f"has_audio:      {info.has_audio}")
    print(f"reels_eligible: {info.reels_eligible}")
    return 0 if (info.media_type == "image" or info.has_audio) else 2


def main(argv: list[str] | None = None) -> int:
    _setup_logging()
    parser = argparse.ArgumentParser(prog="igbot")
    sub = parser.add_subparsers(dest="command", required=True)

    p_fetch = sub.add_parser("fetch", help="fetch + download + enqueue candidates")
    p_fetch.add_argument("--config", default="config.toml")
    p_fetch.add_argument("--limit", type=int, default=None)
    p_fetch.set_defaults(func=cmd_fetch)

    p_probe = sub.add_parser("probe", help="download one URL and report audio status")
    p_probe.add_argument("url")
    p_probe.add_argument("--type", choices=["video", "image"], default="video")
    p_probe.add_argument("--work-dir", default="./work")
    p_probe.set_defaults(func=cmd_probe)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (FileNotFoundError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
