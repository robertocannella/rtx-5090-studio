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


def _make_background(path, freq, duration):
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", f"sine=frequency={freq}:sample_rate=48000", "-t", str(duration), "-c:a", "pcm_s16le", path],
        check=True, capture_output=True,
    )


def _ffprobe_duration(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


@pytest.fixture
def two_segment_episode(tmp_path):
    paths = manifest_mod.episode_paths(str(tmp_path / "output"), "gap-test")
    manifest_mod.ensure_dirs(paths)
    _make_segment_audio(os.path.join(paths["root"], "audio", "001.mp3"), freq=440.0, duration=2.0)
    _make_segment_audio(os.path.join(paths["root"], "audio", "002.mp3"), freq=330.0, duration=2.0)
    m = {
        "title": "Gap Test",
        "topic": "Gap Test",
        "segments": [
            {"number": 1, "title": "Segment One", "audio": "audio/001.mp3", "video": "video/001.mp4", "status": "complete"},
            {"number": 2, "title": "Segment Two", "audio": "audio/002.mp3", "video": "video/002.mp4", "status": "complete"},
        ],
    }
    return paths, m


@pytest.fixture
def three_segment_episode(tmp_path):
    paths = manifest_mod.episode_paths(str(tmp_path / "output"), "three-gap-test")
    manifest_mod.ensure_dirs(paths)
    _make_segment_audio(os.path.join(paths["root"], "audio", "001.mp3"), freq=440.0, duration=2.0)
    _make_segment_audio(os.path.join(paths["root"], "audio", "002.mp3"), freq=330.0, duration=2.0)
    _make_segment_audio(os.path.join(paths["root"], "audio", "003.mp3"), freq=220.0, duration=2.0)
    m = {
        "title": "Three Gap Test",
        "topic": "Three Gap Test",
        "segments": [
            {"number": 1, "title": "Segment One", "audio": "audio/001.mp3", "video": "video/001.mp4", "status": "complete"},
            {"number": 2, "title": "Segment Two", "audio": "audio/002.mp3", "video": "video/002.mp4", "status": "complete"},
            {"number": 3, "title": "Segment Three", "audio": "audio/003.mp3", "video": "video/003.mp4", "status": "complete"},
        ],
    }
    return paths, m


def test_two_gaps_do_not_inflate_final_duration(three_segment_episode):
    # Regression test: ffmpeg's concat *demuxer* (-f concat) was found to badly
    # miscalculate output duration once 2+ short clips (segment gaps) appear in the
    # sequence -- a true ~10s sequence (3x2s segments + 2x1.5s gaps) came out at ~14.6s
    # with the demuxer on this project's ffmpeg build. build_episode_video must use the
    # concat *filter* instead, which doesn't have this failure mode.
    paths, m = three_segment_episode
    final_path = os.path.join(paths["final"], "three-gap-test.mp4")

    video.build_episode_video(paths, m, final_path, gap_seconds=1.5)

    duration = _ffprobe_duration(final_path)
    assert duration == pytest.approx(3 * 2.0 + 2 * 1.5, abs=0.3)  # 9.0s, not ~14s+


@pytest.mark.parametrize("value", [-0.1, 10.1, float("nan"), float("inf"), float("-inf")])
def test_validate_gap_seconds_rejects_invalid(value):
    with pytest.raises(video.VideoError):
        video.validate_gap_seconds(value)


@pytest.mark.parametrize("value", [0.0, 1.5, 2.0, 10.0])
def test_validate_gap_seconds_accepts_in_range(value):
    assert video.validate_gap_seconds(value) == value


def test_zero_gap_matches_prior_behavior(two_segment_episode):
    paths, m = two_segment_episode
    final_path = os.path.join(paths["final"], "gap-test.mp4")

    video.build_episode_video(paths, m, final_path, gap_seconds=0.0)

    assert not os.path.exists(os.path.join(paths["video"], ".gap.mp4"))
    duration = _ffprobe_duration(final_path)
    assert duration == pytest.approx(4.0, abs=0.2)  # two 2s segments, no gap


def test_gap_extends_final_duration_between_segments(two_segment_episode):
    paths, m = two_segment_episode
    final_path = os.path.join(paths["final"], "gap-test.mp4")

    video.build_episode_video(paths, m, final_path, gap_seconds=1.5)

    assert os.path.exists(os.path.join(paths["video"], ".gap.mp4"))
    duration = _ffprobe_duration(final_path)
    assert duration == pytest.approx(4.0 + 1.5, abs=0.2)  # two 2s segments + one 1.5s gap


def test_single_segment_gets_no_gap_even_when_requested(two_segment_episode):
    paths, m = two_segment_episode
    m["segments"] = m["segments"][:1]  # only one complete segment -- nothing to insert a gap between
    final_path = os.path.join(paths["final"], "gap-test.mp4")

    video.build_episode_video(paths, m, final_path, gap_seconds=2.0)

    assert not os.path.exists(os.path.join(paths["video"], ".gap.mp4"))
    duration = _ffprobe_duration(final_path)
    assert duration == pytest.approx(2.0, abs=0.2)


def test_background_music_continues_through_the_gap(two_segment_episode):
    paths, m = two_segment_episode
    final_path = os.path.join(paths["final"], "gap-test.mp4")
    music_path = os.path.join(paths["root"], "music.wav")
    # Prepared for the full narration-plus-gap duration, as pipeline.py's apply_music does.
    _make_background(music_path, freq=110.0, duration=4.0 + 1.5)

    video.build_episode_video(paths, m, final_path, music_audio_path=music_path, gap_seconds=1.5)

    duration = _ffprobe_duration(final_path)
    assert duration == pytest.approx(4.0 + 1.5, abs=0.2)

    # Sample audio energy right in the middle of the gap: should be near-silent narration
    # but the background sine tone keeps it well above true silence.
    gap_midpoint = 2.0 + 0.75
    result = subprocess.run(
        [
            "ffmpeg", "-y", "-ss", str(gap_midpoint), "-i", final_path, "-t", "0.5",
            "-af", "volumedetect", "-f", "null", "-",
        ],
        capture_output=True, text=True,
    )
    assert "mean_volume" in result.stderr
    mean_volume_db = float(
        [line for line in result.stderr.splitlines() if "mean_volume" in line][0].split(":")[1].strip().split(" ")[0]
    )
    assert mean_volume_db > -50  # background music audible, not silence
