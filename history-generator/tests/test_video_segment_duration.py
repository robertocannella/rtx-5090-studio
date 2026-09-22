import os
import subprocess

import manifest as manifest_mod
import pytest
import video


def _make_audio(path, duration=3.0, freq=440.0):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", f"sine=frequency={freq}:duration={duration}", "-c:a", "libmp3lame", path],
        check=True, capture_output=True,
    )


def _stream_durations(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,duration", "-of", "csv=p=0", path],
        capture_output=True, text=True, check=True,
    )
    durations = {}
    for line in out.stdout.strip().splitlines():
        codec_type, duration = line.split(",")
        durations[codec_type] = float(duration)
    return durations


def test_segment_video_and_audio_streams_end_together(tmp_path):
    # Regression test: -shortest alone (the old implementation) let the video stream
    # from the infinite lavfi color source run ~1.8-2s longer than the narration audio,
    # baking a silent tail onto every segment. build_segment_video must now pin an
    # explicit -t to the probed narration duration so both streams match.
    paths = manifest_mod.episode_paths(str(tmp_path), "duration-test")
    manifest_mod.ensure_dirs(paths)
    audio_path = os.path.join(paths["root"], "audio", "001.mp3")
    _make_audio(audio_path, duration=3.0)

    seg = {"number": 1, "title": "Segment One", "audio": "audio/001.mp3", "video": "video/001.mp4"}
    video_path = video.build_segment_video(paths, "Duration Test", seg)

    durations = _stream_durations(video_path)
    assert durations["video"] == pytest.approx(durations["audio"], abs=0.15)
    assert durations["video"] == pytest.approx(3.0, abs=0.15)
