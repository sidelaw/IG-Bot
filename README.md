# IG-Bot

Content sourcing & repackaging tool for landscaping Instagram accounts. Pulls top
posts from Reddit (and later X / optional TikTok), lets an operator review and
assign each one to a target IG account, then publishes via the Instagram Graph
API.

> **Not legal advice.** Read the risk and terms notes below before using this with
> real accounts.

## Status

Built milestone by milestone (see `CLAUDE.md` for the full order).

| # | Milestone | State |
|---|-----------|-------|
| 1 | Reddit fetch + yt-dlp/ffmpeg download with **audio working** | ✅ done |
| 2 | SQLite store + dedup | ✅ schema + store landed, wired into fetch |
| 3 | Public media host (S3/R2) + IG publish (single happy path) | ✅ code-complete, unit-tested (not live-verified) |
| 4 | Review queue (FastAPI): caption, brand overlay, routing, publish | ✅ done |
| 5 | Add second source (X / Twitter) | ✅ code-complete, unit-tested (needs paid API to run) |
| 6 | TikTok module (optional, isolated) | ☐ next |

## The audio fix (milestone 1)

Reddit `v.redd.it` videos store video and audio as **separate streams** —
grabbing only the video gives silence. `src/igbot/media/downloader.py` lets
`yt-dlp` select `bv*+ba/b` and merge with `ffmpeg`, which locates and muxes the
audio automatically. No hand-rolled stream fetcher.

Verified locally (`tests/test_downloader.py`): audio survives normalization,
silent clips stay silent, MP4 is written H.264/AAC with the `moov` atom at the
front (`+faststart`), images convert to JPEG, and Reels eligibility (5–90 s,
9:16) is computed. A *live* `v.redd.it` fetch needs outbound network + Reddit
credentials, which the build sandbox doesn't have.

## Setup

```bash
pip install -e .            # or: pip install -r requirements.txt
# system ffmpeg + ffprobe must be on PATH (not a pip package)

cp config.example.toml config.toml   # edit feeds / accounts (no secrets here)
cp .env.example .env                 # put credentials here (gitignored)
```

Secrets live in environment variables only (see `.env.example`); a PreToolUse
hook blocks commits that contain token-shaped material.

## Usage

```bash
# Fetch + download + enqueue candidates from every configured feed
python -m igbot fetch --limit 10

# Prove the audio fix on a single URL (downloads + reports audio status)
python -m igbot probe "https://www.reddit.com/r/<sub>/comments/<id>/"

# Publish a queued candidate to one account (uploads to the host, then IG)
python -m igbot publish <candidate_id> --account acct_main

# Review queue (the operator gate): edit caption, toggle brand overlay,
# route to accounts, approve, and publish — http://127.0.0.1:8000
python -m igbot review
```

## Review queue (milestone 4)

`igbot review` serves a one-page FastAPI app. Each pending candidate shows a
preview, source + author attribution, score, and Reels/audio badges, with an
editable caption, a **brand-overlay** toggle, and account-routing checkboxes
("which post → which account"). Buttons: Save, Approve, Reject, Publish.
Nothing publishes without passing through here (unless blind mode is added).

When a candidate's brand overlay is on, publishing first burns the configured
`[brand]` text/logo onto the media (ffmpeg for video — audio preserved,
`+faststart`; Pillow for images → JPEG) — the "material edit" the brief ties to
reach. It does **not** address copyright.

## Publishing (milestone 3)

`publish` uploads the normalized file to the configured S3/R2 host (Instagram
needs a public URL), then runs the 3-step Graph dance on `graph.instagram.com`:
create container → poll `?fields=status_code` until `FINISHED` → `media_publish`.

- **Rate limits are queried, never hardcoded** — `content_publishing_limit` is
  read before each publish and the run is refused if the quota is exhausted.
  `X-App-Usage` / `X-Business-Use-Case-Usage` headers are parsed on every
  response and the client backs off as usage climbs.
- **Reels vs feed video** — a Reels-eligible video (5–90 s, 9:16) publishes as a
  Reel (`media_type=REELS`); anything else still publishes, as a feed video, and
  the runner logs a warning rather than failing silently.
- Per-account secrets come from env: `IGBOT_TOKEN_<ID>` + `IGBOT_IGID_<ID>`;
  host keys via `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`.

> Code-complete and unit-tested against a fake transport; a live publish needs
> real credentials + app review (publishing to accounts you don't own).

## Verified terms & risks (eyes open)

- **Reach** — IG suppresses reposts without material edits. The transform step
  (edited caption + optional brand overlay) addresses this; watermarks /
  "credit to…" alone do **not** count.
- **Copyright** — the transform step does **not** fix copyright. Lowest-risk
  content is the landscaper's own footage (job sites, before/afters).
- **Reddit terms** — the free API tier is **non-commercial**; a commercial
  product needs written approval + a paid contract, and since 2025 even personal
  apps need pre-approval. Redistribution may breach the Developer Terms.
- **X** — pay-per-use since Feb 2026 (~$0.005/post read). Reading is sanctioned;
  redistribution carries its own terms. Source uses API v2 recent search
  (`tweet.fields=public_metrics` for scoring, `media.fields=variants` for the
  mp4 URL — video `media.url` is null, the file lives in `variants`). Each run
  is billed per post read, so keep queries tight. Needs `X_BEARER_TOKEN`.
- **TikTok** — no official download path; scraping breaks ToS. Kept walled off,
  off by default.

## Instagram publishing (chosen flow)

**Instagram Login** — host `graph.instagram.com`, Instagram-user token,
permissions `instagram_business_basic` + `instagram_business_content_publish`.
No linked Facebook Page required. JPEG-only images; media must be on a public
URL. **Rate limits are not hardcoded** — the publisher (milestone 3) will query
`content_publishing_limit` and read `X-App-Usage` / `X-Business-Use-Case-Usage`
headers. App review is required to publish to accounts you don't own.

## Layout

```
src/igbot/
  config.py            TOML settings + env-only secrets
  models.py            Candidate dataclass
  pipeline.py          milestone-1 fetch pipeline
  cli.py               `python -m igbot`
  db/                  SQLite schema + store (dedup, queue, routing, tokens)
  sources/             reddit.py, x.py (+ base Source protocol)
  media/               downloader.py (audio fix + normalize), host.py (S3/R2),
                       overlay.py (brand overlay)
  publish/             instagram.py (Graph publish), runner.py (orchestration)
  web/                 app.py (FastAPI review queue)
tests/                 downloader, store, instagram, publish-runner, overlay,
                       pipeline, web tests (32)
.claude/hooks/         block-secrets.sh (commit guard)
```
