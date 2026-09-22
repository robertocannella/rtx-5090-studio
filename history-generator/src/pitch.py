"""Pitch-shifting for narration audio, independent of narration speaking speed.

Applied with ffmpeg's `rubberband` filter (tempo=1.0, so speaking speed/duration is
preserved) to each segment's raw Kokoro narration, producing a separate file used for
video assembly. The original Kokoro output is never modified or re-synthesized.
"""

import math
import subprocess

MIN_SEMITONES = -4.0
MAX_SEMITONES = 4.0


class PitchError(Exception):
    pass


def _run(cmd):
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise PitchError(f"command failed: {' '.join(cmd)}\n{result.stderr[-2000:]}")


def validate(pitch_semitones):
    """Coerce to float and enforce the finite, in-range contract. Raises PitchError."""
    try:
        value = float(pitch_semitones)
    except (TypeError, ValueError) as e:
        raise PitchError(f"pitch_semitones must be a number, got {pitch_semitones!r}") from e
    if not math.isfinite(value):
        raise PitchError(f"pitch_semitones must be finite, got {value}")
    if not (MIN_SEMITONES <= value <= MAX_SEMITONES):
        raise PitchError(
            f"pitch_semitones must be between {MIN_SEMITONES} and {MAX_SEMITONES}, got {value}"
        )
    return value


def pitch_factor(pitch_semitones):
    return 2 ** (pitch_semitones / 12)


_availability_cache = {}


def available():
    """Whether the local ffmpeg build supports the rubberband audio filter."""
    if "ok" not in _availability_cache:
        result = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True)
        _availability_cache["ok"] = "rubberband" in result.stdout
    return _availability_cache["ok"]


def shift(input_path, output_path, pitch_semitones):
    """Pitch-shift input_path by pitch_semitones into output_path, preserving duration/tempo."""
    if not available():
        raise PitchError(
            "ffmpeg does not support the 'rubberband' audio filter (built without "
            "--enable-librubberband) -- cannot apply a nonzero pitch_semitones"
        )
    factor = pitch_factor(pitch_semitones)
    cmd = [
        "ffmpeg", "-y",
        "-i", input_path,
        "-filter:a", f"rubberband=pitch={factor}:tempo=1.0",
        "-c:a", "libmp3lame", "-b:a", "192k",
        output_path,
    ]
    _run(cmd)
    return output_path
