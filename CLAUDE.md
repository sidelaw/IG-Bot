# IG-Bot — Content Sourcing & Repackaging Tool (landscaping IG accounts)

A tool that pulls top posts from Reddit / X / (optional) TikTok, lets an operator
review and reassign each one to a target Instagram account, then publishes it.

## Hard constraints (do not violate)

These are verified against primary sources (Meta dev docs, Reddit API terms, X
pricing). Platform APIs change often and model knowledge is frequently stale —
**verify against official docs / live endpoints before coding any integration.**

- **Never commit API keys, tokens, or secrets.** Secrets come from environment
  variables only. The `igbot.db` file (which holds tokens) is gitignored. A
  PreToolUse hook (`.claude/hooks/block-secrets.sh`) blocks commits that contain
  secret-looking material — do not disable it.
- **Images: JPEG only.** Instagram rejects PNG. Convert before hosting.
- **Media must be on a public URL.** Instagram fetches media by cURLing a public
  URL, so every file must be uploaded to a public host (S3 / R2 / CDN) before
  publishing. (Video may alternatively use the resumable upload endpoint.)
- **Reels target: 5–90 s, 9:16.** Longer/other-aspect clips still publish, but as
  a regular feed video, not a Reel. Surface eligibility; don't silently fail.
- **Do NOT hardcode Instagram rate limits.** Meta's docs give conflicting numbers
  (100 / 50 / 25 posts/24h). Query the `content_publishing_limit` endpoint at
  runtime and respect what it returns. For call rate, read the `X-App-Usage` and
  `X-Business-Use-Case-Usage` response headers and back off as they climb.
- **Reddit `v.redd.it` video has separate video + audio streams.** Grabbing only
  the video gives silence. Use `yt-dlp` (format `bv*+ba/b`) + `ffmpeg` to locate
  and **mux the audio automatically**. Do NOT hand-roll a stream fetcher.
- **Instagram audio:** a video's own baked-in (original) audio uploads fine. You
  **cannot** attach IG's trending/licensed library sounds via the API. Source
  audio carries through; trending sounds do not.

## Normalization target

Transcode video to MP4, H.264 (or HEVC) + AAC, `moov` atom at front
(`+faststart`). Convert images to JPEG.

## Auth flow (chosen)

**Instagram Login** — host `graph.instagram.com`, Instagram-user access token,
permissions `instagram_business_basic` + `instagram_business_content_publish`.
No linked Facebook Page required. (Facebook Login is the alternative, only needed
for Page-linked features.)

## Risk framing (surface to the operator, don't bury)

1. **Reach** — IG suppresses reposts without material edits. The transform step
   (edited caption + optional brand overlay) addresses this. Watermarks / "credit
   to…" alone do not count.
2. **Copyright** — the transform step does NOT fix copyright. Lowest-risk content
   is the landscaper's own footage (job sites, before/afters).
3. **Sourcing terms** — none of the three sources is cleanly permitted for
   commercial redistribution. Eyes open. (Not legal advice.)

## Stack

Python 3.11+ · `praw` (Reddit) · `yt-dlp` + system `ffmpeg` (video, audio fix) ·
`Pillow` (image→JPEG) · `requests` (Graph API) · `sqlite3` (state/dedup/queue/
routing/tokens) · `fastapi` (review UI, later milestone). Config in TOML
(read with stdlib `tomllib`); secrets in env.

## Build order (status)

1. ✅ Reddit fetch + yt-dlp/ffmpeg download with audio working
2. ✅ SQLite store + dedup (schema landed; wired into fetch)
3. ✅ Public media host (S3/R2) + IG publish to one account (single happy
   path) — code-complete & unit-tested; not yet live-verified (needs creds)
4. ✅ Review queue (FastAPI): caption edit, brand overlay, account routing,
   approve → publish — `igbot review`
5. ☐ Add second source (X) — **next**
6. ☐ TikTok module (optional, isolated, off by default)
