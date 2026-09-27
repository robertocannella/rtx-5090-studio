#!/usr/bin/env bash
# Private repo: commits to a new feature branch, pushes it, opens a PR against master,
# and squash-merges it -- rather than committing straight to master. Showcase repo:
# regenerates the redacted export (scripts/export-showcase.sh) and pushes it straight to
# master, since it's a mechanical redaction of content the private-repo PR already
# covered, not new work that needs its own review step.
#
# Usage: scripts/publish.sh "commit message" [branch-name] [showcase-dir]
#   branch-name defaults to a slug derived from the commit message's first line.
#   showcase-dir defaults to ~/history-generator-showcase.

set -euo pipefail

MSG="${1:-}"
if [ -z "$MSG" ]; then
  echo "Usage: $0 \"commit message\" [branch-name] [showcase-dir]" >&2
  exit 1
fi

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SHOWCASE="${3:-$HOME/history-generator-showcase}"
TITLE="$(echo "$MSG" | head -1)"

# A relative $SHOWCASE is always a mistake -- there's no legitimate case for it, and one
# has already caused real damage: a stray quote inside a commit message argument once
# split it off the message string as its own word, silently turning $SHOWCASE into a
# short relative fragment. That resolved under $SRC (since the script cd's there and
# never leaves), so the showcase export wrote into a brand new subdirectory of THIS repo
# instead of the separate public repo, and the commit/push below then pushed it straight
# to master. Refusing early makes that fail loudly instead.
case "$SHOWCASE" in
  /*) ;;
  *)
    echo "SHOWCASE must be an absolute path, got: $SHOWCASE" >&2
    exit 1
    ;;
esac
if [ ! -d "$SHOWCASE/.git" ]; then
  echo "SHOWCASE does not look like a git repo (no .git found): $SHOWCASE" >&2
  exit 1
fi

if [ -n "${2:-}" ]; then
  BRANCH="$2"
else
  BRANCH="feature/$(echo "$TITLE" | tr '[:upper:]' '[:lower:]' | tr -c 'a-z0-9' '-' | sed 's/-\+/-/g; s/^-//; s/-$//' | cut -c1-50)"
fi

refuse_if_env_staged() {
  local bad
  bad="$(git diff --cached --name-only | grep -iE '(^|/)\.env(\..*)?$' || true)"
  if [ -n "$bad" ]; then
    echo "   REFUSING to commit -- staged .env file(s) found:" >&2
    echo "$bad" | sed 's/^/     /' >&2
    git reset -q
    exit 1
  fi
}

cd "$SRC"
echo "== private repo: branch $BRANCH =="
git add -A
refuse_if_env_staged

if git diff --cached --quiet; then
  echo "   no changes to commit"
else
  git checkout -q -b "$BRANCH"
  git commit -q -m "$MSG"
  git push -q -u origin "$BRANCH"
  echo "   pushed branch $BRANCH"

  gh pr create --title "$TITLE" --body "$MSG" --base master --head "$BRANCH" >/dev/null
  gh pr merge "$BRANCH" --squash --delete-branch >/dev/null
  git checkout -q master
  git pull -q origin master
  git fetch -q --prune origin  # gh's --delete-branch removes it on GitHub; this clears our now-stale local tracking ref for it
  echo "   opened PR, squash-merged into master, deleted $BRANCH"
fi

echo "== refreshing showcase export =="
"$SRC/scripts/export-showcase.sh" "$SHOWCASE"

echo "== public showcase repo ($SHOWCASE) =="
cd "$SHOWCASE"
git add -A
refuse_if_env_staged

if git diff --cached --quiet; then
  echo "   no changes to commit"
else
  git commit -q -m "$MSG"
  git push -q
  echo "   pushed"
fi

echo
echo "Done."
