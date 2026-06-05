# First-time setup guide

Plain-English, step-by-step. The goal: go from "code on disk" to "actually
posting to Instagram." Do the steps in order. You can stop after Step 3 if you
only want to test the fetching/review parts without posting yet.

> **Secrets rule:** every password/key/token goes in the `.env` file (Step 2)
> or your cloud provider's settings — **never** typed into chat, commits, or
> `config.toml`. A commit hook will block you if you slip.

---

## Step 0 — What you need a computer to have

- **Python 3.11+** — check with `python3 --version`.
- **ffmpeg** (includes `ffprobe`) — check with `ffmpeg -version`. Install:
  - Mac: `brew install ffmpeg`
  - Ubuntu/Debian: `sudo apt-get install ffmpeg`
  - Windows: download from ffmpeg.org and add it to PATH.

Then, in the project folder:

```bash
pip install -e .          # installs the tool + core libraries
pip install -e ".[host,ui]"   # also installs S3/R2 upload + the review web page
```

Sanity check it runs:

```bash
python -m igbot --help
```

---

## Step 1 — Make your two config files

```bash
cp config.example.toml config.toml
cp .env.example .env
```

- `config.toml` = your settings (which subreddits, which accounts, etc.). No
  secrets here.
- `.env` = your secret keys. Both are git-ignored, so they won't get committed.

You'll fill these in as you go through the steps below.

---

## Step 2 — A public place to put media (Cloudflare R2 — ~free to start)

Instagram will only accept a photo/video if it can download it from a public web
link. So files get uploaded to cloud storage first. **Cloudflare R2** is the
cheapest easy option (Amazon S3 works too — same settings).

1. Make a free Cloudflare account → **R2** → **Create bucket** (e.g.
   `my-igbot-media`).
2. Turn on **public access** for the bucket (R2 → your bucket → Settings →
   "Public Development URL", or connect a custom domain). Copy that public URL.
3. R2 → **Manage API Tokens** → create a token with **Object Read & Write**.
   You'll get an **Access Key ID** and **Secret Access Key**.
4. Find your **account endpoint**, which looks like
   `https://<account-id>.r2.cloudflarestorage.com`.

Now fill in `config.toml` under `[host]`:

```toml
[host]
provider = "s3"
bucket = "my-igbot-media"
region = "auto"
endpoint_url = "https://<account-id>.r2.cloudflarestorage.com"
public_base_url = "https://<your-public-bucket-url>"
key_prefix = "igbot"
```

And in `.env`:

```
AWS_ACCESS_KEY_ID=<the Access Key ID from step 3>
AWS_SECRET_ACCESS_KEY=<the Secret Access Key from step 3>
```

(Those AWS-named variables are just the standard names the upload library uses;
they work for R2 too.)

---

## Step 3 — (Optional) content sources: Reddit and X

You can skip this entirely if you'll only post your **own** footage (see the
shortcut at the bottom — strongly recommended).

**Reddit** (free for testing; a real business needs a paid agreement with Reddit):
1. Go to <https://www.reddit.com/prefs/apps> → **create an app** → type
   **script**.
2. Copy the **client id** (under the app name) and the **secret**.
3. Put them in `.env`:
   ```
   REDDIT_CLIENT_ID=...
   REDDIT_CLIENT_SECRET=...
   ```

**X / Twitter** (costs money — about half a cent per post it reads):
1. Sign up at the X developer portal and get a **Bearer token**.
2. Put it in `.env`:
   ```
   X_BEARER_TOKEN=...
   ```

In `config.toml`, edit the `[[feeds]]` blocks to point at the subreddits /
search terms you want, and set `target_accounts` to your account id.

---

## Step 4 — Instagram (the big one — plan ~2 weeks)

This is the part that takes the most patience, because Meta has to approve your
app before it will let software post.

1. **Account type:** your Instagram account must be **Professional** (Business
   or Creator). Switch in the IG app: Settings → Account type.
2. **Meta app:** go to <https://developers.facebook.com>, create an app, and add
   the **Instagram** product using **"Instagram API with Instagram Login."**
3. **Permissions:** your app needs `instagram_business_basic` and
   `instagram_business_content_publish`.
4. **App Review:** to publish, Meta requires you to submit the app for review.
   They'll want a short **screen recording** showing the posting flow. Budget
   about **two weeks**. (You can do limited testing before this with your own
   account added as a tester.)
5. **Get your token + account id:** after auth you'll have an **Instagram-user
   access token** and your **IG user id**. Put them in `.env`, named after your
   account id from `config.toml` (here the id is `acct_main`):
   ```
   IGBOT_TOKEN_ACCT_MAIN=<the access token>
   IGBOT_IGID_ACCT_MAIN=<your IG user id>
   ```

In `config.toml`, set the account block:

```toml
[[accounts]]
id = "acct_main"
username = "your_account"
auth_flow = "instagram_login"
```

And optionally set your brand overlay text (used when you toggle "brand overlay"
on a post):

```toml
[brand]
text = "@your_account"
position = "bottom-right"
```

---

## Step 5 — Run it

```bash
# 1) Pull candidate posts from your sources, download + clean them up
python -m igbot fetch

# 2) Open the review page in your browser (http://127.0.0.1:8000):
#    edit captions, toggle the brand overlay, pick which account each goes to,
#    then Approve. NOTHING posts until you press Publish.
python -m igbot review

# 3) Publish a specific approved post to its account
python -m igbot publish <candidate_number> --account acct_main
```

There's also a quick test command that downloads one video and tells you whether
the audio came through (handy for checking Reddit videos):

```bash
python -m igbot probe "https://www.reddit.com/r/<sub>/comments/<id>/"
```

---

## The shortcut worth taking ✅

If the landscaper films **their own** job sites (before/afters, fly-throughs),
you can **skip Steps 3 entirely** (no Reddit/X keys, no scraping) and avoid the
copyright and terms-of-service headaches completely. You'd only need:

- Step 0 (computer + ffmpeg),
- Step 2 (R2 bucket),
- Step 4 (Instagram),
- and you'd feed the tool your own video files.

This is the safest and simplest way to use it.

---

## Honest warnings

- **Legal/terms:** reposting other people's Reddit/X/TikTok content for a
  business is a copyright and terms grey area; none of the three clearly allows
  it. Adding a logo/caption helps Instagram *reach* but does **not** fix
  copyright. (Not legal advice.)
- **TikTok** is off by default on purpose — it relies on scraping that breaks
  TikTok's rules and breaks often. Leave it off unless you really mean it.
- **Rate limits** are read from Instagram at runtime, so the tool won't post
  past your account's daily cap.
