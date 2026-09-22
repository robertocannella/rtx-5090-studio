import os
import subprocess
from types import SimpleNamespace

import manifest as manifest_mod
import pipeline


def _make_raw_audio(path):
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=220:duration=1", "-c:a", "libmp3lame", path],
        check=True, capture_output=True,
    )


def _episode(tmp_path):
    paths = manifest_mod.episode_paths(str(tmp_path), "test-episode")
    manifest_mod.ensure_dirs(paths)
    _make_raw_audio(os.path.join(paths["root"], "audio", "001.mp3"))
    m = {
        "segments": [
            {
                "number": 1,
                "title": "Segment One",
                "audio": "audio/001.mp3",
                "video": "video/001.mp4",
                "status": "complete",
                "duration": 1.0,
            }
        ]
    }
    return paths, m


def _touch_video(paths, m):
    video_path = os.path.join(paths["root"], m["segments"][0]["video"])
    with open(video_path, "wb") as f:
        f.write(b"fake-video-bytes")
    return video_path


def test_apply_pitch_skips_ffmpeg_when_unchanged_at_zero(tmp_path, monkeypatch):
    paths, m = _episode(tmp_path)
    seg = m["segments"][0]

    calls = []
    monkeypatch.setattr(pipeline.pitch, "shift", lambda *a, **kw: calls.append(a))

    pipeline.apply_pitch_to_segments(SimpleNamespace(pitch_semitones=0.0), paths, m)

    assert calls == []
    assert seg.get("audio_pitched") is None
    assert seg.get("pitch_semitones") in (None, 0.0)


def test_apply_pitch_invalidation_lifecycle(tmp_path, monkeypatch):
    paths, m = _episode(tmp_path)
    seg = m["segments"][0]

    real_shift = pipeline.pitch.shift
    calls = []

    def spy_shift(*args, **kwargs):
        calls.append(args)
        return real_shift(*args, **kwargs)

    monkeypatch.setattr(pipeline.pitch, "shift", spy_shift)

    # 1. First request at +2.0 semitones -> shifts once, video (which didn't exist yet) stays absent.
    pipeline.apply_pitch_to_segments(SimpleNamespace(pitch_semitones=2.0), paths, m)
    assert len(calls) == 1
    assert seg["pitch_semitones"] == 2.0
    pitched_path = os.path.join(paths["root"], seg["audio_pitched"])
    assert os.path.getsize(pitched_path) > 0
    pitched_mtime = os.path.getmtime(pitched_path)

    # 2. Simulate a segment video having been built from that pitched narration.
    video_path = _touch_video(paths, m)

    # 3. Re-running with the SAME pitch must not re-shift narration or touch the video.
    pipeline.apply_pitch_to_segments(SimpleNamespace(pitch_semitones=2.0), paths, m)
    assert len(calls) == 1  # no new shift call
    assert os.path.getmtime(pitched_path) == pitched_mtime
    assert os.path.exists(video_path)

    # 4. Changing pitch must re-shift and invalidate (delete) the stale per-segment video,
    #    without needing to touch the original raw Kokoro audio.
    raw_path = os.path.join(paths["root"], seg["audio"])
    raw_mtime_before = os.path.getmtime(raw_path)
    pipeline.apply_pitch_to_segments(SimpleNamespace(pitch_semitones=-1.0), paths, m)
    assert len(calls) == 2
    assert seg["pitch_semitones"] == -1.0
    assert not os.path.exists(video_path)  # invalidated
    assert os.path.getmtime(raw_path) == raw_mtime_before  # raw narration untouched

    # 5. Dropping back to 0 must not call ffmpeg (pure skip), but must still invalidate
    #    the video (since it was built from pitch-shifted audio) and clear audio_pitched.
    video_path = _touch_video(paths, m)
    pipeline.apply_pitch_to_segments(SimpleNamespace(pitch_semitones=0.0), paths, m)
    assert len(calls) == 2  # no new shift call for pitch=0
    assert seg["pitch_semitones"] == 0.0
    assert seg.get("audio_pitched") is None
    assert not os.path.exists(video_path)  # invalidated back to raw audio

    # 6. Re-running at 0 again with nothing changed must be a true no-op.
    video_path = _touch_video(paths, m)
    pipeline.apply_pitch_to_segments(SimpleNamespace(pitch_semitones=0.0), paths, m)
    assert len(calls) == 2
    assert os.path.exists(video_path)  # left alone this time
