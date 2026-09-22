import os
from types import SimpleNamespace

import manifest as manifest_mod
import pipeline


def _episode(tmp_path, visual_style="static", visual=None):
    paths = manifest_mod.episode_paths(str(tmp_path), "visual-test")
    manifest_mod.ensure_dirs(paths)
    m = {
        "visual_style": visual_style,
        "segments": [
            {
                "number": 1,
                "title": "Segment One",
                "audio": "audio/001.mp3",
                "video": "video/001.mp4",
                "status": "complete",
            },
        ],
    }
    if visual is not None:
        m["visual"] = visual
    return paths, m


def _touch(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"fake-bytes")


def _ns(visual_style):
    return SimpleNamespace(visual_style=visual_style)


def test_noop_when_style_unchanged_static(tmp_path):
    paths, m = _episode(tmp_path, visual_style="static")
    video_path = os.path.join(paths["root"], m["segments"][0]["video"])
    _touch(video_path)
    mtime = os.path.getmtime(video_path)

    pipeline.apply_visual_to_segments(_ns("static"), paths, m, "visual-test")

    assert "visual" not in m
    assert os.path.getmtime(video_path) == mtime


def test_switching_to_math_selects_a_visual_and_invalidates_video(tmp_path):
    paths, m = _episode(tmp_path, visual_style="static")
    video_path = os.path.join(paths["root"], m["segments"][0]["video"])
    _touch(video_path)

    pipeline.apply_visual_to_segments(_ns("math"), paths, m, "visual-test")

    assert m["visual"]["family"] in ("waves", "fourier", "trace")
    assert m["visual_style"] == "math"
    assert not os.path.exists(video_path)


def test_switching_to_math_is_deterministic_for_the_same_slug(tmp_path):
    paths1, m1 = _episode(tmp_path, visual_style="static")
    pipeline.apply_visual_to_segments(_ns("math"), paths1, m1, "same-slug")

    paths2, m2 = _episode(tmp_path, visual_style="static")
    pipeline.apply_visual_to_segments(_ns("math"), paths2, m2, "same-slug")

    assert m1["visual"] == m2["visual"]


def test_resuming_with_math_unchanged_does_not_reselect_or_touch_video(tmp_path):
    existing_visual = {"family": "waves", "params": {"curves": []}, "seed": "visual-test"}
    paths, m = _episode(tmp_path, visual_style="math", visual=existing_visual)
    video_path = os.path.join(paths["root"], m["segments"][0]["video"])
    _touch(video_path)
    mtime = os.path.getmtime(video_path)

    pipeline.apply_visual_to_segments(_ns("math"), paths, m, "visual-test")

    assert m["visual"] == existing_visual  # not re-rolled
    assert os.path.getmtime(video_path) == mtime  # not invalidated


def test_switching_off_math_invalidates_video_but_keeps_the_stored_visual(tmp_path):
    existing_visual = {"family": "trace", "params": {"a": 3, "b": 2}, "seed": "visual-test"}
    paths, m = _episode(tmp_path, visual_style="math", visual=existing_visual)
    video_path = os.path.join(paths["root"], m["segments"][0]["video"])
    _touch(video_path)
    math_bg_path = os.path.join(paths["video"], ".math_bg.mp4")
    _touch(math_bg_path)

    pipeline.apply_visual_to_segments(_ns("static"), paths, m, "visual-test")

    assert m["visual_style"] == "static"
    assert m["visual"] == existing_visual  # kept around, just not used
    assert not os.path.exists(video_path)
    assert not os.path.exists(math_bg_path)


def test_switching_math_off_then_back_on_reuses_the_original_selection(tmp_path):
    paths, m = _episode(tmp_path, visual_style="static")
    pipeline.apply_visual_to_segments(_ns("math"), paths, m, "visual-test")
    first_visual = m["visual"]

    pipeline.apply_visual_to_segments(_ns("static"), paths, m, "visual-test")
    pipeline.apply_visual_to_segments(_ns("math"), paths, m, "visual-test")

    assert m["visual"] == first_visual


def test_failed_segment_without_video_file_is_not_reported_as_touched(tmp_path):
    paths, m = _episode(tmp_path, visual_style="static")
    m["segments"][0]["status"] = "failed"
    # No video file on disk for this segment.
    pipeline.apply_visual_to_segments(_ns("math"), paths, m, "visual-test")
    assert m["visual_style"] == "math"
