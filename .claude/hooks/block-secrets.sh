#!/usr/bin/env bash
# PreToolUse hook: block git commits/adds that would introduce secrets.
# Reads the tool call JSON on stdin. Exit 2 = block (message on stderr).
#
# Defense in depth alongside .gitignore. Scans the *staged* diff for
# token-shaped material and refuses sensitive filenames.
set -uo pipefail

input="$(cat)"

# Extract the bash command from the tool input (stdlib python, always present).
cmd="$(printf '%s' "$input" | python3 -c 'import sys,json
try:
    print(json.load(sys.stdin).get("tool_input",{}).get("command",""))
except Exception:
    print("")' 2>/dev/null)"

# Only police git add / git commit. Everything else passes through.
case "$cmd" in
  *"git add"*|*"git commit"*|*"git stage"*) ;;
  *) exit 0 ;;
esac

# Make sure the index reflects what's about to be committed for `git add -A`/`-u`.
staged="$(git diff --cached -U0 2>/dev/null)"
# Also consider files newly added on this command line (best effort).
[ -z "$staged" ] && exit 0

# Refuse obviously-sensitive staged filenames. Template files (*.example) are
# safe placeholders and are explicitly allowed (e.g. .env.example).
bad_files="$(git diff --cached --name-only 2>/dev/null \
  | grep -Ev '\.example$' \
  | grep -Ei '(^|/)(\.env($|\.)|.*\.pem$|.*\.key$|secrets\.toml$|.*credentials.*)' || true)"
if [ -n "$bad_files" ]; then
  echo "BLOCKED: refusing to commit sensitive file(s):" >&2
  echo "$bad_files" >&2
  echo "Secrets belong in environment variables, not the repo." >&2
  exit 2
fi

# Token-shaped patterns in the staged additions.
hits="$(printf '%s' "$staged" | grep -nE \
  -e 'IGAA[A-Za-z0-9_-]{20,}' \
  -e 'EAA[A-Za-z0-9]{20,}' \
  -e 'AKIA[0-9A-Z]{16}' \
  -e '-----BEGIN [A-Z ]*PRIVATE KEY-----' \
  -e '(client_secret|access_token|refresh_token|api_key|apikey|password|reddit_secret)["'"'"' ]*[:=]["'"'"' ]*[A-Za-z0-9/+_-]{12,}' \
  -e 'Bearer [A-Za-z0-9._-]{20,}' \
  | grep -viE 'os\.environ|getenv|env\[|EXAMPLE|REPLACE_ME|<your|placeholder|\.example' || true)"

if [ -n "$hits" ]; then
  echo "BLOCKED: staged changes look like they contain a secret:" >&2
  printf '%s\n' "$hits" | head -20 >&2
  echo "Use environment variables. If this is a false positive, rename/rephrase." >&2
  exit 2
fi

exit 0
