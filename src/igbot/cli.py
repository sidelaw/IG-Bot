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


def cmd_publish(args: argparse.Namespace) -> int:
    from .publish.runner import publish_candidate

    cfg = config_mod.load(args.config)
    media_id = publish_candidate(cfg, args.candidate, args.account)
    print(f"Published candidate {args.candidate} to {args.account} -> media {media_id}")
    return 0


def cmd_post(args: argparse.Namespace) -> int:
    """Publish your own local video/photo straight to Instagram."""
    from .publish.runner import publish_local_file

    cfg = config_mod.load(args.config)
    media_id = publish_local_file(
        cfg, args.file, account_id=args.account,
        caption=args.caption, brand_overlay=args.brand,
    )
    print(f"\n✅ Posted to {args.account}! Instagram media id: {media_id}")
    return 0


def cmd_harvest(args: argparse.Namespace) -> int:
    """Daily: pull the top posts from each Reddit feed into the queue."""
    from .automation import harvest

    cfg = config_mod.load(args.config)
    added = harvest(cfg)
    print(f"Harvested {len(added)} new post(s) into the queue.")
    return 0


def cmd_post_next(args: argparse.Namespace) -> int:
    """Every interval: publish the next queued item to its account."""
    from .automation import post_next

    cfg = config_mod.load(args.config)
    media_id = post_next(cfg)
    if media_id:
        print(f"✅ Posted next queued item -> media {media_id}")
    else:
        print("Nothing posted (queue empty or deferred).")
    return 0


def cmd_review(args: argparse.Namespace) -> int:
    import uvicorn

    from .web import create_app

    cfg = config_mod.load(args.config)
    app = create_app(cfg)
    print(f"Review queue on http://{args.host}:{args.port}  (mode: {cfg.mode})")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
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

    p_pub = sub.add_parser("publish", help="publish a queued candidate to an account")
    p_pub.add_argument("candidate", type=int, help="candidate id")
    p_pub.add_argument("--account", required=True, help="target account id")
    p_pub.add_argument("--config", default="config.toml")
    p_pub.set_defaults(func=cmd_publish)

    p_post = sub.add_parser("post", help="publish your own local video/photo to Instagram")
    p_post.add_argument("file", help="path to your video or image file")
    p_post.add_argument("--account", default="acct_main", help="account id (default acct_main)")
    p_post.add_argument("--caption", default="", help="the Instagram caption")
    p_post.add_argument("--brand", action="store_true", help="burn on the brand overlay")
    p_post.add_argument("--config", default="config.toml")
    p_post.set_defaults(func=cmd_post)

    p_harv = sub.add_parser("harvest", help="[automation] queue the top Reddit posts")
    p_harv.add_argument("--config", default="config.toml")
    p_harv.set_defaults(func=cmd_harvest)

    p_next = sub.add_parser("post-next", help="[automation] publish the next queued item")
    p_next.add_argument("--config", default="config.toml")
    p_next.set_defaults(func=cmd_post_next)

    p_rev = sub.add_parser("review", help="serve the FastAPI review queue")
    p_rev.add_argument("--config", default="config.toml")
    p_rev.add_argument("--host", default="127.0.0.1")
    p_rev.add_argument("--port", type=int, default=8000)
    p_rev.set_defaults(func=cmd_review)

    p_probe = sub.add_parser("probe", help="download one URL and report audio status")
    p_probe.add_argument("url")
    p_probe.add_argument("--type", choices=["video", "image"], default="video")
    p_probe.add_argument("--work-dir", default="./work")
    p_probe.set_defaults(func=cmd_probe)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
