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


def _episode(tmp_path, voice="af_heart", speed=1.0, sentence_gap_seconds=0.0):
    paths = manifest_mod.episode_paths(str(tmp_path), "test-episode")
    manifest_mod.ensure_dirs(paths)
    _make_raw_audio(os.path.join(paths["root"], "audio", "001.mp3"))
    m = {
        "voice": voice,
        "speed": speed,
        "sentence_gap_seconds": sentence_gap_seconds,
        "segments": [
            {
                "number": 1,
                "title": "Segment One",
                "script": "scripts/001.txt",
                "audio": "audio/001.mp3",
                "video": "video/001.mp4",
                "status": "complete",
                "duration": 1.0,
            },
            {
                "number": 2,
                "title": "Segment Two",
                "script": "scripts/002.txt",
                "audio": "audio/002.mp3",
                "video": "video/002.mp4",
                "status": "pending",
                "duration": None,
            },
        ],
    }
    return paths, m


def _touch(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"fake-bytes")


def _ns(voice="af_heart", speed=1.0, sentence_gap_seconds=0.0):
    return SimpleNamespace(voice=voice, speed=speed, sentence_gap_seconds=sentence_gap_seconds)


def test_noop_when_all_unchanged(tmp_path):
    paths, m = _episode(tmp_path)
    audio_path = os.path.join(paths["root"], m["segments"][0]["audio"])
    audio_mtime = os.path.getmtime(audio_path)

    pipeline.apply_narration_params_to_segments(_ns(), paths, m)

    assert m["segments"][0]["status"] == "complete"
    assert os.path.getmtime(audio_path) == audio_mtime


def test_voice_change_resets_completed_segment(tmp_path):
    paths, m = _episode(tmp_path)
    seg = m["segments"][0]
    audio_path = os.path.join(paths["root"], seg["audio"])
    video_path = os.path.join(paths["root"], seg["video"])
    script_path = os.path.join(paths["root"], seg["script"])
    _touch(video_path)
    _touch(script_path)

    pipeline.apply_narration_params_to_segments(_ns(voice="am_adam"), paths, m)

    assert seg["status"] == "pending"
    assert seg["duration"] is None
    assert not os.path.exists(audio_path)
    assert not os.path.exists(video_path)
    assert os.path.exists(script_path)  # script text is unaffected
    assert m["voice"] == "am_adam"


def test_speed_change_resets_completed_segment(tmp_path):
    paths, m = _episode(tmp_path)
    seg = m["segments"][0]
    audio_path = os.path.join(paths["root"], seg["audio"])
    video_path = os.path.join(paths["root"], seg["video"])
    _touch(video_path)

    pipeline.apply_narration_params_to_segments(_ns(speed=0.85), paths, m)

    assert seg["status"] == "pending"
    assert not os.path.exists(audio_path)
    assert not os.path.exists(video_path)
    assert m["speed"] == 0.85


def test_sentence_gap_change_resets_completed_segment(tmp_path):
    paths, m = _episode(tmp_path, sentence_gap_seconds=0.0)
    seg = m["segments"][0]
    audio_path = os.path.join(paths["root"], seg["audio"])
    video_path = os.path.join(paths["root"], seg["video"])
    script_path = os.path.join(paths["root"], seg["script"])
    _touch(video_path)
    _touch(script_path)

    pipeline.apply_narration_params_to_segments(_ns(sentence_gap_seconds=0.5), paths, m)

    assert seg["status"] == "pending"
    assert not os.path.exists(audio_path)
    assert not os.path.exists(video_path)
    assert os.path.exists(script_path)  # script text is unaffected
    assert m["sentence_gap_seconds"] == 0.5


def test_segment_gap_alone_does_not_trigger_narration_reset(tmp_path):
    # segment_gap_seconds isn't a narration param at all -- apply_narration_params_to_segments
    # doesn't even look at it, so it must never be the reason narration gets reset.
    paths, m = _episode(tmp_path)
    seg = m["segments"][0]
    audio_path = os.path.join(paths["root"], seg["audio"])
    audio_mtime = os.path.getmtime(audio_path)

    pipeline.apply_narration_params_to_segments(_ns(), paths, m)

    assert seg["status"] == "complete"
    assert os.path.getmtime(audio_path) == audio_mtime


def test_change_also_clears_pitch_shifted_audio(tmp_path):
    paths, m = _episode(tmp_path)
    seg = m["segments"][0]
    pitched_rel = "audio/001.pitch.mp3"
    pitched_path = os.path.join(paths["root"], pitched_rel)
    _touch(pitched_path)
    seg["audio_pitched"] = pitched_rel
    seg["pitch_semitones"] = 2.0

    pipeline.apply_narration_params_to_segments(_ns(voice="am_adam"), paths, m)

    assert not os.path.exists(pitched_path)
    assert seg["audio_pitched"] is None
    assert "pitch_semitones" not in seg


def test_pending_segment_without_files_is_left_alone(tmp_path):
    paths, m = _episode(tmp_path)
    pending = m["segments"][1]

    pipeline.apply_narration_params_to_segments(_ns(voice="am_adam"), paths, m)

    assert pending["status"] == "pending"
    assert pending["duration"] is None


def test_failed_segment_is_reset_for_retry(tmp_path):
    paths, m = _episode(tmp_path)
    seg = m["segments"][0]
    seg["status"] = "failed"
    seg["error"] = "kokoro timeout"

    pipeline.apply_narration_params_to_segments(_ns(voice="am_adam"), paths, m)

    assert seg["status"] == "pending"
    assert "error" not in seg


def test_manifest_values_updated_even_with_no_segments_to_reset(tmp_path):
    paths, m = _episode(tmp_path)
    m["segments"] = []

    pipeline.apply_narration_params_to_segments(_ns(voice="am_adam", speed=1.1, sentence_gap_seconds=0.5), paths, m)

    assert m["voice"] == "am_adam"
    assert m["speed"] == 1.1
    assert m["sentence_gap_seconds"] == 0.5
