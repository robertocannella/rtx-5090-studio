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


def _make_image(path, color):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c={color}:s=64x36", "-frames:v", "1", path],
        check=True, capture_output=True,
    )


def _ffprobe_duration(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


@pytest.fixture
def thumbnail_episode(tmp_path):
    paths = manifest_mod.episode_paths(str(tmp_path / "output"), "thumbnail-video-test")
    manifest_mod.ensure_dirs(paths)
    _make_segment_audio(os.path.join(paths["root"], "audio", "001.mp3"), freq=440.0, duration=3.0)
    _make_segment_audio(os.path.join(paths["root"], "audio", "002.mp3"), freq=330.0, duration=4.5)
    _make_image(os.path.join(paths["images"], "thumbnail.png"), "purple")
    m = {
        "title": "Thumbnail Video Test",
        "topic": "Thumbnail Video Test",
        "thumbnail_image": "images/thumbnail.png",
        "segments": [
            {
                "number": 1, "title": "Segment One", "audio": "audio/001.mp3", "video": "video/001.mp4",
                "status": "complete",
            },
            {
                "number": 2, "title": "Segment Two", "audio": "audio/002.mp3", "video": "video/002.mp4",
                "status": "complete",
            },
        ],
    }
    return paths, m


def test_thumbnail_style_uses_the_same_image_for_every_segment(thumbnail_episode):
    paths, m = thumbnail_episode
    final_path = os.path.join(paths["final"], "thumbnail-video-test.mp4")

    video.build_episode_video(paths, m, final_path, gap_seconds=1.5, visual_style="thumbnail")

    assert os.path.exists(final_path)
    assert _ffprobe_duration(final_path) == pytest.approx(3.0 + 4.5 + 1.5, abs=0.3)
    # Neither segment has its own "images" list (unlike visual_style="images") -- both
    # must still get a real background built from the one shared thumbnail_image.
    assert _ffprobe_duration(os.path.join(paths["root"], "video/001.mp4")) == pytest.approx(3.0, abs=0.2)
    assert _ffprobe_duration(os.path.join(paths["root"], "video/002.mp4")) == pytest.approx(4.5, abs=0.2)


def test_thumbnail_ignored_when_visual_style_is_not_thumbnail(thumbnail_episode):
    paths, m = thumbnail_episode
    final_path = os.path.join(paths["final"], "thumbnail-video-test.mp4")

    # Even though thumbnail_image is present in the manifest, a different visual_style
    # must not use it -- same "ignored unless selected" behavior as visual_style="images".
    video.build_episode_video(paths, m, final_path, gap_seconds=1.5, visual_style="static")

    assert os.path.exists(final_path)
    assert _ffprobe_duration(final_path) == pytest.approx(3.0 + 4.5 + 1.5, abs=0.3)


def test_thumbnail_noop_when_visual_style_is_thumbnail_but_none_generated_yet(thumbnail_episode):
    paths, m = thumbnail_episode
    del m["thumbnail_image"]
    final_path = os.path.join(paths["final"], "thumbnail-video-test.mp4")

    # Shouldn't happen in practice (pipeline.py generates it before build_episode_video
    # ever runs), but must degrade to the plain static background rather than crash.
    video.build_episode_video(paths, m, final_path, gap_seconds=1.5, visual_style="thumbnail")

    assert os.path.exists(final_path)
