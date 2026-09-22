"""Local background-music catalog: discovery, fingerprinting, and safety-review gating.

catalog.json lives inside the music library itself (e.g. /srv/media/audio/music/catalog.json,
mounted read-only into the containers) and is the only source of truth for which tracks
exist and whether a human has approved them for automatic ("sleep-safe") selection.
Nothing here downloads, deletes, or renames source audio files -- scan() only reads them.
"""

import hashlib
import json
import os
import re
import subprocess

CATALOG_FILENAME = "catalog.json"
SUPPORTED_EXTS = {".mp3", ".wav", ".flac", ".ogg", ".m4a"}


class CatalogError(Exception):
    pass


def sha256_file(path, block_size=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(block_size), b""):
            h.update(chunk)
    return h.hexdigest()


def _ffprobe_duration(path):
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
        capture_output=True, text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return None
    try:
        return round(float(result.stdout.strip()), 3)
    except ValueError:
        return None


def catalog_path(library_dir):
    return os.path.join(library_dir, CATALOG_FILENAME)


def load(library_dir):
    path = catalog_path(library_dir)
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return json.load(f)


def save(library_dir, entries):
    path = catalog_path(library_dir)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(entries, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


def _find_license_file(full_path):
    """Best-effort: a Pixabay-style '<...>-<numeric id>-license.txt' next to the track,
    matched by the numeric id shared with the track's own filename. Never assumed to
    exist; scan() never treats its absence as meaningful."""
    directory = os.path.dirname(full_path)
    stem = os.path.splitext(os.path.basename(full_path))[0]
    digits = re.findall(r"\d+", stem)
    if not digits:
        return None
    track_num = digits[-1]
    try:
        siblings = os.listdir(directory)
    except OSError:
        return None
    for name in siblings:
        if "license" in name.lower() and track_num in name:
            return os.path.join(directory, name)
    return None


def _parse_pixabay_license(text):
    """Pull only facts explicitly printed in the certificate -- never a license verdict."""
    info = {}
    m = re.search(r"Licensor's Username:\s*\n?\s*(https?://\S+)", text)
    if m:
        info["creator"] = m.group(1)
    m = re.search(r"Audio File URL:\s*\n?\s*(https?://\S+)", text)
    if m:
        info["source_url"] = m.group(1)
    return info


def _new_entry(rel, full, library_dir, fingerprint, duration):
    category = os.path.dirname(rel).split(os.sep)[0] if os.path.dirname(rel) else "uncategorized"
    entry = {
        "id": fingerprint[:12],
        "title": os.path.splitext(os.path.basename(rel))[0],
        "file": rel,
        "category": category,
        "tags": [category],
        "mood": category,
        "energy": None,
        "vocals": None,
        "percussion": None,
        "sleep_safe": False,
        "creator": None,
        "source_url": None,
        "license": None,
        "license_file": None,
        "duration_seconds": duration,
        "fingerprint": fingerprint,
    }
    license_file = _find_license_file(full)
    if license_file:
        entry["license_file"] = os.path.relpath(license_file, library_dir)
        try:
            with open(license_file, encoding="utf-8", errors="replace") as f:
                entry.update(_parse_pixabay_license(f.read()))
        except OSError:
            pass
    return entry


def scan(library_dir):
    """Discover audio files under library_dir and merge them into catalog.json.

    - Existing entries (matched by relative file path) keep all human-edited fields
      (sleep_safe, energy, vocals, percussion, tags, ...) untouched, except that a
      changed audio fingerprint resets sleep_safe to False (the approved review no
      longer applies to whatever content is now at that path).
    - New files are added as unreviewed (sleep_safe: false); nothing about license or
      suitability is ever inferred from a filename or folder name.
    - Entries whose file is currently missing are kept (not deleted) so re-plugging a
      drive or restoring a file doesn't lose prior review metadata, but they're
      unselectable until the file exists again (resolve_track() checks on disk).

    Byte-identical files (matching fingerprint) at different paths are cataloged once;
    later duplicates are reported in the "duplicates" summary key rather than given a
    second entry -- otherwise they'd collide on the same derived id.

    Returns a summary dict:
    {"added": [...], "updated": [...], "missing": [...], "duplicates": [...], "total": n}.
    """
    if not os.path.isdir(library_dir):
        raise CatalogError(f"music library directory not found: {library_dir}")

    existing = load(library_dir)
    by_file = {e["file"]: e for e in existing}
    fingerprint_to_file = {e["fingerprint"]: e["file"] for e in existing if e.get("fingerprint")}

    found = []
    for root, _dirs, files in os.walk(library_dir):
        for name in files:
            if os.path.splitext(name)[1].lower() not in SUPPORTED_EXTS:
                continue
            full = os.path.join(root, name)
            rel = os.path.relpath(full, library_dir)
            found.append((rel, full))
    found.sort()

    seen = set()
    added, updated, duplicates = [], [], []
    result = []
    for rel, full in found:
        seen.add(rel)
        fingerprint = sha256_file(full)
        duration = _ffprobe_duration(full)
        entry = by_file.get(rel)
        if entry is None:
            canonical = fingerprint_to_file.get(fingerprint)
            if canonical and canonical != rel:
                duplicates.append({"file": rel, "duplicate_of": canonical})
                continue
            entry = _new_entry(rel, full, library_dir, fingerprint, duration)
            fingerprint_to_file[fingerprint] = rel
            added.append(rel)
        else:
            if entry.get("fingerprint") != fingerprint:
                entry["sleep_safe"] = False
                updated.append(rel)
            entry["fingerprint"] = fingerprint
            fingerprint_to_file[fingerprint] = rel
            if duration is not None:
                entry["duration_seconds"] = duration
        result.append(entry)

    missing = [rel for rel in by_file if rel not in seen]
    for rel in missing:
        result.append(by_file[rel])

    result.sort(key=lambda e: e["file"])
    save(library_dir, result)
    return {
        "added": added, "updated": updated, "missing": missing,
        "duplicates": duplicates, "total": len(result),
    }
