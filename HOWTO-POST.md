# How to post (browser / Codespaces)

A short checklist for posting your own video or photo. No installing anything.

## One-time: add your secrets to GitHub
Repo → **Settings → Secrets and variables → Codespaces → New repository secret**.
Add these (left = exact name, right = your value):

| Secret name | Value |
|---|---|
| `IGBOT_TOKEN_ACCT_MAIN` | your Instagram token |
| `IGBOT_IGID_ACCT_MAIN` | your Instagram account id |
| `AWS_ACCESS_KEY_ID` | your R2 Access Key ID |
| `AWS_SECRET_ACCESS_KEY` | your R2 Secret Access Key |
| `R2_BUCKET` | your bucket name |
| `R2_ENDPOINT_URL` | `https://<id>.r2.cloudflarestorage.com` |
| `R2_PUBLIC_BASE_URL` | your bucket's public URL (e.g. `https://pub-….r2.dev`) |

> Secrets go HERE, never in chat or in the code. If you ever paste a key
> somewhere public, rotate it (make a new one) immediately.

## Open the workspace
Repo → green **`< > Code`** → **Codespaces** → **Create codespace on main**.
Wait ~2–3 min for it to finish setting up. A terminal opens at the bottom.

(If you added the secrets *after* opening the Codespace, rebuild it so they load:
Command Palette → "Codespaces: Rebuild Container".)

## Post
1. Drag your video/photo into the file list on the left (e.g. `test.mp4`).
2. In the terminal:
   ```
   python -m igbot post test.mp4 --caption "Test from my new tool 🌱"
   ```
3. Success looks like: `✅ Posted to acct_main! Instagram media id: …`

### Options
- Add your brand overlay (set `[brand] text` in `config.toml` first):
  ```
  python -m igbot post test.mp4 --caption "..." --brand
  ```
- Best as a **Reel**: vertical 9:16, 5–90 seconds. Other clips still post, just
  as a regular feed video.

## If it errors
Copy the error text (NOT your keys) and send it over — common ones:
- *no token / no IG user id* → the Instagram secrets aren't set, or you didn't
  rebuild the Codespace after adding them.
- *host.bucket is not configured* → the R2 secrets aren't set.
- *not Reels-eligible* → just a notice; it still posts as a feed video.
