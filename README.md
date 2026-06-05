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
| 3 | Public media host + IG publish (single happy path) | ☐ next |
| 4 | Review queue: caption edit, brand overlay, account routing | ☐ |
| 5 | Add second source (X) | ☐ |
| 6 | TikTok module (optional, isolated) | ☐ |

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
```

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
  redistribution carries its own terms.
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
  sources/             reddit.py (+ base Source protocol)
  media/               downloader.py (the audio fix + normalize)
tests/                 downloader + store tests
.claude/hooks/         block-secrets.sh (commit guard)
```
