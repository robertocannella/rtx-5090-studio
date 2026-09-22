"""CLI: scan the local music library and update its catalog.json.

    python3 scan_music.py [--library-dir /app/audio-library/music]

Run this after adding/removing/replacing files in the music library, and again after
manually reviewing new entries in catalog.json (setting sleep_safe/vocals/percussion/
energy) so the generator can auto-select them. See docs/HISTORY-GENERATOR.md's
"Background Music" section.
"""

import argparse
import os
import sys

import music_catalog


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument(
        "--library-dir", default=os.environ.get("MUSIC_LIBRARY_DIR", "/app/audio-library/music"),
        help="Path to the music library (default: $MUSIC_LIBRARY_DIR or /app/audio-library/music)",
    )
    args = p.parse_args(argv if argv is not None else sys.argv[1:])

    try:
        summary = music_catalog.scan(args.library_dir)
    except music_catalog.CatalogError as e:
        print(f"[error] {e}")
        return 1

    print(f"Library: {args.library_dir}")
    print(f"Catalog: {music_catalog.catalog_path(args.library_dir)}")
    print(f"Total tracks: {summary['total']}")
    if summary["added"]:
        print(f"Added ({len(summary['added'])}):")
        for rel in summary["added"]:
            print(f"  + {rel}")
    if summary["updated"]:
        print(f"Content changed, sleep_safe reset to false ({len(summary['updated'])}):")
        for rel in summary["updated"]:
            print(f"  ~ {rel}")
    if summary["missing"]:
        print(f"On record but file missing, kept for review ({len(summary['missing'])}):")
        for rel in summary["missing"]:
            print(f"  ? {rel}")
    if summary["duplicates"]:
        print(f"Byte-identical duplicates skipped, not cataloged separately ({len(summary['duplicates'])}):")
        for dup in summary["duplicates"]:
            print(f"  = {dup['file']}  (same content as {dup['duplicate_of']})")
    if summary["added"]:
        print()
        print(
            "New tracks are unreviewed (sleep_safe: false) and won't be auto-selected. "
            "Listen to them, then edit catalog.json to set sleep_safe/vocals/percussion/"
            "energy before they can be picked automatically -- or select one explicitly "
            "with music_track_id in the meantime."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
