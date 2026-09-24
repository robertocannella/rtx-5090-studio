#!/usr/bin/env bash
# Hardlinks each finished episode's canonical final video into /srv/media/generated-episodes/
# so it shows up in a Jellyfin library pointed at that folder. Zero extra disk space (same
# filesystem, hardlinks) and idempotent (safe to re-run any time).
#
# Only links output/<slug>/final/<slug>.mp4 where the filename stem exactly matches the
# episode slug -- this naturally excludes backup directories (e.g.
# "<slug>.pre-*-backup-.../final/<slug>.mp4") and comparison-render files (e.g.
# "<slug>/final/<slug>.sentence-gap-0.mp4"), since neither matches that pattern.
#
# Re-links (doesn't just skip) when the source's content has changed -- e.g. a --force
# regeneration writes a brand-new final.mp4 (new inode) while the OLD hardlink in
# LIBRARY_DIR is a separate directory entry to the old inode that survives independently
# and would otherwise keep showing Jellyfin stale content forever. Detected by comparing
# device:inode, not mtime/size, so it's correct even if a regenerated episode happens to
# land on the same size by coincidence.
#
# Also prunes hardlinks whose source episode no longer exists in OUTPUT_DIR at all (e.g.
# deleted via the Configuration UI's "Delete episode" -- see api.py's DELETE
# /episodes/{slug}, which only removes the episode's own output directory, not this
# separate hardlink tree). Deleting an episode doesn't remove it from Jellyfin
# immediately -- it disappears on this script's next scheduled run (every 15 minutes via
# cron, see crontab -l), not instantly.
set -euo pipefail

OUTPUT_DIR="/srv/apps/history-generator/output"
LIBRARY_DIR="/srv/media/generated-episodes"

mkdir -p "$LIBRARY_DIR"

linked=0
relinked=0
for f in "$OUTPUT_DIR"/*/final/*.mp4; do
  [ -e "$f" ] || continue
  slug=$(basename "$(dirname "$(dirname "$f")")")
  base=$(basename "$f" .mp4)
  if [ "$base" = "$slug" ]; then
    target="$LIBRARY_DIR/${slug}.mp4"
    if [ ! -e "$target" ]; then
      ln "$f" "$target"
      echo "linked: $slug"
      linked=$((linked + 1))
    elif [ "$(stat -c '%d:%i' "$f")" != "$(stat -c '%d:%i' "$target")" ]; then
      ln -f "$f" "$target"
      echo "relinked (content changed): $slug"
      relinked=$((relinked + 1))
    fi
  fi
done

pruned=0
for link in "$LIBRARY_DIR"/*.mp4; do
  [ -e "$link" ] || continue
  slug=$(basename "$link" .mp4)
  if [ ! -e "$OUTPUT_DIR/$slug/final/$slug.mp4" ]; then
    rm -f "$link"
    echo "pruned (source deleted): $slug"
    pruned=$((pruned + 1))
  fi
done

echo "$linked new episode(s) linked, $relinked updated for changed content, $pruned pruned for deleted episodes."
