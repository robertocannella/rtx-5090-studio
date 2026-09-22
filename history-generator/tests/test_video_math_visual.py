import os
import subprocess

import manifest as manifest_mod
import math_visual as mv
import pytest
import video


def _make_segment_audio(path, freq=440.0, duration=2.0):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", f"sine=frequency={freq}:duration={duration}", "-c:a", "libmp3lame", path],
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
    paths = manifest_mod.episode_paths(str(tmp_path / "output"), "math-video-test")
    manifest_mod.ensure_dirs(paths)
    _make_segment_audio(os.path.join(paths["root"], "audio", "001.mp3"), freq=440.0, duration=2.0)
    _make_segment_audio(os.path.join(paths["root"], "audio", "002.mp3"), freq=330.0, duration=2.0)
    m = {
        "title": "Math Video Test",
        "topic": "Math Video Test",
        "segments": [
            {"number": 1, "title": "Segment One", "audio": "audio/001.mp3", "video": "video/001.mp4", "status": "complete"},
            {"number": 2, "title": "Segment Two", "audio": "audio/002.mp3", "video": "video/002.mp4", "status": "complete"},
        ],
    }
    return paths, m


def test_visual_none_behaves_exactly_as_before(two_segment_episode):
    # Regression check: passing visual=None (the default) must take the old, static-
    # background code path -- no .math_bg.mp4 should ever be created.
    paths, m = two_segment_episode
    final_path = os.path.join(paths["final"], "math-video-test.mp4")

    video.build_episode_video(paths, m, final_path, gap_seconds=1.5)

    assert os.path.exists(final_path)
    assert not os.path.exists(os.path.join(paths["video"], ".math_bg.mp4"))
    assert _ffprobe_duration(final_path) == pytest.approx(4.0 + 1.5, abs=0.3)


def test_math_visual_renders_background_and_correct_duration(two_segment_episode):
    paths, m = two_segment_episode
    final_path = os.path.join(paths["final"], "math-video-test.mp4")
    # "waves" is the fastest family to render -- pin it explicitly to keep this test fast.
    visual = {"family": "waves", "params": mv._PARAM_BUILDERS["waves"](__import__("random").Random(1)), "seed": "math-video-test"}

    video.build_episode_video(paths, m, final_path, gap_seconds=1.5, visual=visual)

    math_bg_path = os.path.join(paths["video"], ".math_bg.mp4")
    assert os.path.exists(math_bg_path)
    assert os.path.exists(final_path)
    assert _ffprobe_duration(final_path) == pytest.approx(4.0 + 1.5, abs=0.3)


def test_math_bg_is_cached_across_calls_unless_forced(two_segment_episode, monkeypatch):
    paths, m = two_segment_episode
    final_path = os.path.join(paths["final"], "math-video-test.mp4")
    visual = {"family": "waves", "params": mv._PARAM_BUILDERS["waves"](__import__("random").Random(2)), "seed": "math-video-test"}

    video.build_episode_video(paths, m, final_path, gap_seconds=1.5, visual=visual)
    math_bg_path = os.path.join(paths["video"], ".math_bg.mp4")
    assert os.path.exists(math_bg_path)

    calls = []
    real_render_loop = video.math_visual.render_loop

    def spy_render_loop(*args, **kwargs):
        calls.append(args)
        return real_render_loop(*args, **kwargs)

    monkeypatch.setattr(video.math_visual, "render_loop", spy_render_loop)

    # Re-running with unchanged segment videos (still cached) and the same visual must
    # not re-render the already-cached background.
    video.build_episode_video(paths, m, final_path, gap_seconds=1.5, visual=visual)
    assert len(calls) == 0

    # force=True must re-render it.
    video.build_episode_video(paths, m, final_path, gap_seconds=1.5, visual=visual, force=True)
    assert len(calls) == 1
