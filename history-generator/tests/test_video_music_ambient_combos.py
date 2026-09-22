import os
import subprocess

import manifest as manifest_mod
import pytest
import video


def _make_segment_audio(path, freq=440.0, duration=2.0):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", f"sine=frequency={freq}:duration={duration}", "-c:a", "libmp3lame", path],
        check=True, capture_output=True,
    )


def _make_background(path, freq, duration=2.0):
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", f"sine=frequency={freq}:sample_rate=48000", "-t", str(duration), "-c:a", "pcm_s16le", path],
        check=True, capture_output=True,
    )


def _has_audio_stream(path):
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=codec_type", "-of", "csv=p=0", path],
        capture_output=True, text=True, check=True,
    )
    return "audio" in result.stdout


@pytest.fixture
def episode(tmp_path):
    paths = manifest_mod.episode_paths(str(tmp_path / "output"), "combo-test")
    manifest_mod.ensure_dirs(paths)
    _make_segment_audio(os.path.join(paths["root"], "audio", "001.mp3"))
    m = {
        "title": "Combo Test",
        "topic": "Combo Test",
        "segments": [
            {"number": 1, "title": "Segment One", "audio": "audio/001.mp3", "video": "video/001.mp4", "status": "complete"},
        ],
    }
    return paths, m


@pytest.mark.parametrize("use_ambient,use_music", [
    (False, False),
    (True, False),
    (False, True),
    (True, True),
])
def test_all_four_ambient_music_combinations_produce_valid_output(tmp_path, episode, use_ambient, use_music):
    paths, m = episode
    ambient_path = None
    music_path = None
    if use_ambient:
        ambient_path = str(tmp_path / "ambient.wav")
        _make_background(ambient_path, freq=220.0)
    if use_music:
        music_path = str(tmp_path / "music.wav")
        _make_background(music_path, freq=110.0)

    final_path = os.path.join(paths["final"], "combo-test.mp4")
    video.build_episode_video(
        paths, m, final_path, ambient_audio_path=ambient_path, music_audio_path=music_path,
    )

    assert os.path.exists(final_path)
    assert os.path.getsize(final_path) > 0
    assert _has_audio_stream(final_path)

    narrated_intermediate = os.path.join(paths["video"], ".narrated.mp4")
    if use_ambient or use_music:
        # Background mixing happens as a distinct final pass over an intermediate file.
        assert os.path.exists(narrated_intermediate)
    else:
        # Narration-only: the concat step writes straight to final_path, no mix pass.
        assert not os.path.exists(narrated_intermediate)
