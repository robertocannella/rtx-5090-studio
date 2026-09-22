"""Background music: catalog-driven track selection and audio preparation.

Tracks come from a local, human-curated library (see music_catalog.py for the scanner)
-- never downloaded, generated, or guessed at generation time. Selection is deterministic
per episode (seeded by the episode slug) so re-running the same episode doesn't pick a
different track. Preparation (loop/trim to the episode's actual length, loudness-normalize,
fade, level) happens with ffmpeg and is cached like everything else in this pipeline.
"""

import hashlib
import math
import os
import subprocess

import music_catalog

MIN_LEVEL_DB = -40.0
MAX_LEVEL_DB = -6.0

AUTO_SELECT_ENERGY = ("very-low", "low")


class MusicError(Exception):
    pass


def _run(cmd):
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise MusicError(f"command failed: {' '.join(cmd)}\n{result.stderr[-2000:]}")


def fingerprint(path):
    return music_catalog.sha256_file(path)


def validate_level_db(value):
    try:
        v = float(value)
    except (TypeError, ValueError) as e:
        raise MusicError(f"music_level_db must be a number, got {value!r}") from e
    if not math.isfinite(v):
        raise MusicError(f"music_level_db must be finite, got {v}")
    if not (MIN_LEVEL_DB <= v <= MAX_LEVEL_DB):
        raise MusicError(f"music_level_db must be between {MIN_LEVEL_DB} and {MAX_LEVEL_DB}, got {v}")
    return v


def validate_fade_seconds(value, name="fade_seconds"):
    try:
        v = float(value)
    except (TypeError, ValueError) as e:
        raise MusicError(f"{name} must be a number, got {value!r}") from e
    if not math.isfinite(v) or v < 0:
        raise MusicError(f"{name} must be a finite number >= 0, got {v}")
    return v


def _resolve_within_library(library_dir, relative_path):
    library_dir = os.path.realpath(library_dir)
    candidate = os.path.realpath(os.path.join(library_dir, relative_path))
    if candidate != library_dir and not candidate.startswith(library_dir + os.sep):
        raise MusicError(f"resolved music path escapes the music library: {relative_path!r}")
    return candidate


def resolve_track(library_dir, track_id=None, mood=None, seed=""):
    """Pick a catalog track. Returns (track_dict, absolute_file_path).

    An explicit track_id bypasses the sleep-safety filters (the caller asked for it by
    name) but still must exist on disk. Mood-based auto-selection only ever considers
    tracks a human has reviewed and approved (sleep_safe/vocals/percussion/energy).
    """
    if not os.path.isdir(library_dir):
        raise MusicError(f"music library directory not found: {library_dir}")

    catalog = music_catalog.load(library_dir)
    if not catalog:
        raise MusicError(
            f"no music catalog found under {library_dir} -- run scan_music.py first"
        )

    if track_id:
        matches = [t for t in catalog if t.get("id") == track_id]
        if not matches:
            raise MusicError(f"unknown music_track_id: {track_id!r}")
        track = matches[0]
    else:
        candidates = [
            t for t in catalog
            if t.get("sleep_safe") is True
            and t.get("vocals") is False
            and t.get("percussion") is False
            and t.get("energy") in AUTO_SELECT_ENERGY
            and (mood is None or mood == t.get("category") or mood in (t.get("tags") or []))
        ]
        if not candidates:
            raise MusicError(
                "no approved music tracks found"
                + (f" for mood {mood!r}" if mood else "")
                + " -- tracks must be reviewed and marked sleep_safe: true, vocals: false, "
                  "percussion: false, energy: very-low/low in catalog.json before they can "
                  "be auto-selected (or pass an explicit music_track_id)"
            )
        candidates.sort(key=lambda t: t["id"])
        idx = int(hashlib.sha256(seed.encode("utf-8")).hexdigest(), 16) % len(candidates)
        track = candidates[idx]

    resolved_path = _resolve_within_library(library_dir, track["file"])
    if not os.path.isfile(resolved_path):
        raise MusicError(f"music track file missing or unreadable: {track['file']}")
    return track, resolved_path


def prepare(track_path, duration_seconds, level_db, fade_in_seconds, fade_out_seconds, out_path):
    """Loop/trim track_path to duration_seconds, loudness-normalize, level, and fade.

    -stream_loop -1 makes a single ffmpeg pass handle both extending a short track
    (looped) and trimming a long one (cut at -t) uniformly. The source file itself is
    never modified.
    """
    duration_seconds = max(1.0, float(duration_seconds))
    level_db = validate_level_db(level_db)
    fade_in = min(validate_fade_seconds(fade_in_seconds, "music_fade_in_seconds"), duration_seconds / 2)
    fade_out = min(validate_fade_seconds(fade_out_seconds, "music_fade_out_seconds"), duration_seconds / 2)
    fade_out_start = max(0.0, duration_seconds - fade_out)

    filters = [
        "loudnorm=I=-23:TP=-2:LRA=11",
        f"volume={level_db}dB",
    ]
    if fade_in > 0:
        filters.append(f"afade=t=in:st=0:d={fade_in:.2f}")
    if fade_out > 0:
        filters.append(f"afade=t=out:st={fade_out_start:.2f}:d={fade_out:.2f}")

    cmd = [
        "ffmpeg", "-y",
        "-stream_loop", "-1", "-i", track_path,
        "-filter:a", ",".join(filters),
        "-ar", "48000", "-ac", "2",
        "-t", f"{duration_seconds:.2f}",
        "-c:a", "pcm_s16le",
        out_path,
    ]
    _run(cmd)
    return out_path
