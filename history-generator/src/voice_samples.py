"""Short preview clips of each Kokoro voice, generated once and cached on disk.

Not part of the narration pipeline -- these exist purely for the Configuration UI's
"preview this voice" button, so someone can hear a voice before picking it for a whole
episode. Reuses kokoro_client.synthesize() for the actual TTS call; a plain ffmpeg -t
trim afterward guarantees the cached clip is never longer than SAMPLE_DURATION_SECONDS
regardless of how a given voice happens to pace the fixed sample text (voices don't all
speak at exactly the same rate for the same words).
"""

import os
import re
import subprocess

import kokoro_client

SAMPLE_TEXT = (
    "The quiet hum of history drifts through time, carrying stories of distant places, "
    "curious discoveries, and the voices that first gave them shape."
)
SAMPLE_DURATION_SECONDS = 10.0

_SAFE_VOICE_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


class VoiceSampleError(Exception):
    pass


def _run(cmd):
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise VoiceSampleError(f"command failed: {' '.join(cmd)}\n{result.stderr[-2000:]}")


def sample_path(samples_dir, voice_id):
    if not _SAFE_VOICE_ID_RE.match(voice_id or ""):
        raise VoiceSampleError(f"invalid voice id: {voice_id!r}")
    return os.path.join(samples_dir, f"{voice_id}.mp3")


def get_or_create(kokoro_url, voice_id, samples_dir):
    """Return the path to a cached <=10s preview clip for voice_id, synthesizing and
    trimming it first if this is the first time it's been requested. Cheap on repeat
    calls (existence check only) -- callers don't need their own caching layer.
    """
    os.makedirs(samples_dir, exist_ok=True)
    path = sample_path(samples_dir, voice_id)
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return path

    audio_bytes = kokoro_client.synthesize(kokoro_url, "kokoro", voice_id, SAMPLE_TEXT, speed=1.0)
    raw_path = path + ".raw"
    with open(raw_path, "wb") as f:
        f.write(audio_bytes)
    try:
        _run([
            "ffmpeg", "-y", "-i", raw_path,
            "-t", f"{SAMPLE_DURATION_SECONDS:.1f}",
            "-c:a", "libmp3lame", "-b:a", "96k",
            path,
        ])
    finally:
        if os.path.exists(raw_path):
            os.remove(raw_path)
    return path
