#!/usr/bin/env bash
# Commits + pushes the private /srv/apps repo, then regenerates and commits + pushes the
# redacted public showcase repo (scripts/export-showcase.sh) -- the two-repo workflow
# from docs/README.md, in one command.
#
# Usage: scripts/publish.sh "commit message" [showcase-dir]
#   (showcase-dir defaults to ~/history-generator-showcase)

set -euo pipefail

MSG="${1:-}"
if [ -z "$MSG" ]; then
  echo "Usage: $0 \"commit message\" [showcase-dir]" >&2
  exit 1
fi

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SHOWCASE="${2:-$HOME/history-generator-showcase}"

commit_and_push() {
  local dir="$1" label="$2"
  echo "== $label ($dir) =="
  cd "$dir"
  git add -A

  # Belt-and-suspenders: .gitignore already excludes these, but never push a commit that
  # somehow staged a real secret file, even if .gitignore was edited or bypassed.
  local bad
  bad="$(git diff --cached --name-only | grep -iE '(^|/)\.env(\..*)?$' || true)"
  if [ -n "$bad" ]; then
    echo "   REFUSING to commit -- staged .env file(s) found:" >&2
    echo "$bad" | sed 's/^/     /' >&2
    git reset -q
    exit 1
  fi

  if git diff --cached --quiet; then
    echo "   no changes to commit"
  else
    git commit -q -m "$MSG"
    echo "   committed: $(git log -1 --oneline)"
  fi
  git push -q
  echo "   pushed"
}

commit_and_push "$SRC" "private repo"

echo "== refreshing showcase export =="
"$SRC/scripts/export-showcase.sh" "$SHOWCASE"

commit_and_push "$SHOWCASE" "public showcase repo"

echo
echo "Done."
