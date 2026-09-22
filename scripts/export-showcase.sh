#!/usr/bin/env bash
# Exports the git-tracked contents of /srv/apps into a separate directory with the real
# domain, admin email, and basic_auth password hashes replaced by generic placeholders --
# for publishing as a public "showcase" repo without exposing this server's real hostname
# or credentials. The live files under /srv/apps (what Caddy/Docker actually read) are
# never touched; only the copy in DEST is rewritten. Re-run this any time you want to
# refresh the public repo after making changes here.
#
# Usage: scripts/export-showcase.sh [DEST]  (default: ~/history-generator-showcase)

set -euo pipefail

DEST="${1:-$HOME/history-generator-showcase}"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

REAL_DOMAIN="example.com"
REAL_EMAIL="user@example.com"
REAL_USERNAME="appuser"
PLACEHOLDER_DOMAIN="example.com"
PLACEHOLDER_EMAIL="user@example.com"
PLACEHOLDER_USERNAME="appuser"
PLACEHOLDER_HASH='$2a$14$XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX'

echo "Exporting tracked files from $SRC to $DEST ..."
mkdir -p "$DEST"
# Clear previously-exported tracked content (but never touch DEST/.git) before re-copying,
# so a file removed from the live repo also disappears from the export on the next run.
find "$DEST" -mindepth 1 -maxdepth 1 ! -name ".git" ! -name ".gitignore" -exec rm -rf {} +

cd "$SRC"
git ls-files -z | while IFS= read -r -d '' f; do
  mkdir -p "$DEST/$(dirname "$f")"
  cp "$f" "$DEST/$f"
done

echo "Redacting real domain/email/username/auth hashes ..."
python3 - "$DEST" "$REAL_DOMAIN" "$PLACEHOLDER_DOMAIN" "$REAL_EMAIL" "$PLACEHOLDER_EMAIL" "$REAL_USERNAME" "$PLACEHOLDER_USERNAME" "$PLACEHOLDER_HASH" <<'PYEOF'
import re
import sys
from pathlib import Path

(dest, real_domain, placeholder_domain, real_email, placeholder_email,
 real_username, placeholder_username, placeholder_hash) = sys.argv[1:9]

# A basic_auth credential line is "<username> <bcrypt-hash>" -- match username and hash
# together (whatever the username is, not just the ones we already know about) so both
# get replaced with equally generic placeholders in one pass, rather than only redacting
# the hash and leaving whatever short/real username sat in front of it.
credential_re = re.compile(r"[^\s]+(\s+)\$2[aby]\$\d{2}\$[./A-Za-z0-9]{53}")

changed = []
for path in Path(dest).rglob("*"):
    if not path.is_file() or path.is_symlink():
        continue
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, ValueError):
        continue  # binary file -- leave untouched
    original = text
    text = credential_re.sub(lambda m: f"user{m.group(1)}{placeholder_hash}", text)
    text = text.replace(real_email, placeholder_email)
    text = text.replace(real_domain, placeholder_domain)
    # Bare username last -- it's a substring of real_email, so replacing it first would
    # have broken the email match above.
    text = text.replace(real_username, placeholder_username)
    if text != original:
        path.write_text(text, encoding="utf-8")
        changed.append(str(path.relative_to(dest)))

print(f"Rewrote {len(changed)} file(s):")
for c in sorted(changed):
    print(f"  {c}")
PYEOF

echo
echo "Done. Review with: cd $DEST && git status"
