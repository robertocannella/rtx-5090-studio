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
def images_episode(tmp_path):
    paths = manifest_mod.episode_paths(str(tmp_path / "output"), "images-video-test")
    manifest_mod.ensure_dirs(paths)
    _make_segment_audio(os.path.join(paths["root"], "audio", "001.mp3"), freq=440.0, duration=3.0)
    _make_segment_audio(os.path.join(paths["root"], "audio", "002.mp3"), freq=330.0, duration=4.5)
    _make_image(os.path.join(paths["images"], "001_00.png"), "red")
    _make_image(os.path.join(paths["images"], "002_00.png"), "blue")
    _make_image(os.path.join(paths["images"], "002_01.png"), "green")
    _make_image(os.path.join(paths["images"], "002_02.png"), "yellow")
    m = {
        "title": "Images Video Test",
        "topic": "Images Video Test",
        "segments": [
            {
                "number": 1, "title": "Segment One", "audio": "audio/001.mp3", "video": "video/001.mp4",
                "status": "complete", "images": ["images/001_00.png"],
            },
            {
                "number": 2, "title": "Segment Two", "audio": "audio/002.mp3", "video": "video/002.mp4",
                "status": "complete", "images": ["images/002_00.png", "images/002_01.png", "images/002_02.png"],
            },
        ],
    }
    return paths, m


def test_images_visual_style_produces_correct_durations(images_episode):
    paths, m = images_episode
    final_path = os.path.join(paths["final"], "images-video-test.mp4")

    video.build_episode_video(paths, m, final_path, gap_seconds=1.5, visual_style="images")

    assert os.path.exists(final_path)
    assert _ffprobe_duration(final_path) == pytest.approx(3.0 + 4.5 + 1.5, abs=0.3)
    # Segment 1 has a single image (no crossfade needed).
    assert _ffprobe_duration(os.path.join(paths["root"], "video/001.mp4")) == pytest.approx(3.0, abs=0.2)
    # Segment 2 crossfades across 3 images but must still land on the narration duration.
    assert _ffprobe_duration(os.path.join(paths["root"], "video/002.mp4")) == pytest.approx(4.5, abs=0.2)


def test_images_ignored_when_visual_style_is_not_images(images_episode):
    paths, m = images_episode
    final_path = os.path.join(paths["final"], "images-video-test.mp4")

    # visual_style defaults to None/"static" -- even though these segments carry an
    # "images" list, build_episode_video must not touch it and must fall back to the
    # plain static background, same as before this feature existed.
    video.build_episode_video(paths, m, final_path, gap_seconds=1.5)

    assert os.path.exists(final_path)
    assert not os.path.exists(os.path.join(paths["video"], ".math_bg.mp4"))
    assert _ffprobe_duration(final_path) == pytest.approx(3.0 + 4.5 + 1.5, abs=0.3)


def test_images_input_and_filter_covers_exact_duration_with_crossfades():
    inputs, filter_complex, label = video._images_input_and_filter(
        ["a.png", "b.png", "c.png"], narration_duration=9.0, resolution="640x360", fps="30",
    )
    assert label == "vimg"
    assert filter_complex.count("xfade=") == 2
    assert inputs.count("-i") == 3


def test_images_input_and_filter_single_image_has_no_crossfade():
    inputs, filter_complex, label = video._images_input_and_filter(
        ["a.png"], narration_duration=5.0, resolution="640x360", fps="30",
    )
    assert label == "s0"
    assert "xfade" not in filter_complex
    assert inputs.count("-i") == 1
