# Automatic posting (hands-off)

Once set up, the bot runs itself in the cloud — no laptop, no terminal:

- **Every day** it checks Reddit and grabs the **top posts** from each subreddit
  you list (the `harvest` job).
- **Every 2 hours** it posts the next one to the right Instagram account
  (the `post-next` job), so they trickle out instead of all at once.

It runs on **GitHub Actions** (free for this public repo) and keeps its queue in
your **Cloudflare R2 bucket**, so nothing depends on your computer being on.

---

## 1. Tell it which subreddit goes to which account
Edit **`config.toml`** — right in the GitHub website (open the file → click the
pencil ✏️ → Commit changes). Each `[[feeds]]` block is "this subreddit → this
account":

```toml
[[feeds]]
subreddits = ["lawncare"]
target_accounts = ["acct_main"]

[[feeds]]
subreddits = ["gardening"]
target_accounts = ["acct_two"]
```

And list each Instagram account once:

```toml
[[accounts]]
id = "acct_main"
[[accounts]]
id = "acct_two"
```

`harvest_count` (top of the file) is how many to grab per subreddit per day.

## 2. Add your secrets (GitHub → Settings → Secrets and variables → Actions)
> Use the **Actions** tab of Secrets (not Codespaces) for the scheduled jobs.
> **Reddit needs no key** — the bot reads the public RSS feed.

| Secret | What |
|---|---|
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | your R2 keys |
| `R2_BUCKET` / `R2_ENDPOINT_URL` / `R2_PUBLIC_BASE_URL` | your bucket |
| `IGBOT_TOKEN_ACCT_MAIN` / `IGBOT_IGID_ACCT_MAIN` | account #1 token + id |
| `IGBOT_TOKEN_ACCT_TWO` / `IGBOT_IGID_ACCT_TWO` | account #2 (if used) |

Each account id in `config.toml` needs a matching `IGBOT_TOKEN_<ID>` and
`IGBOT_IGID_<ID>` (uppercased). To add a 3rd account, add the secrets and add
its two lines to `.github/workflows/post.yml`.

## 3. Turn it on
The schedules are already in the repo (`.github/workflows/harvest.yml` and
`post.yml`). They start running on their own. To test immediately without
waiting:
**Actions tab → "Harvest (daily)" → Run workflow**, then
**"Post (every 2 hours)" → Run workflow**.

---

## Good to know
- **Times are UTC.** Daily harvest is 06:00 UTC; change the `cron` lines if you
  want a different time.
- **Instagram limits:** the bot reads your account's real limit and won't post
  past it — if it's reached, it just waits for the next slot.
- **It won't repost the same Reddit post twice** (it remembers what it's grabbed
  in `state/seen.json` in your bucket).
- **Reach & copyright:** auto-posting other people's Reddit content with no
  review is the riskiest mode (Instagram may limit reach; it doesn't fix
  copyright). Turn on `brand_overlay` and set `[brand] text` for a small edit,
  and keep an eye on the account. (Not legal advice.)
- **GitHub note:** scheduled workflows pause if the repo has no activity for
  ~60 days — just visit/commit to keep them alive, or run them by hand.
