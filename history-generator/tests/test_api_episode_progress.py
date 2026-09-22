import os

import api
import manifest as manifest_mod


def _make_episode(tmp_path, slug="test-episode", with_final=True, segments=None, target_duration_seconds=60, visual_style=None):
    paths = manifest_mod.episode_paths(str(tmp_path), slug)
    manifest_mod.ensure_dirs(paths)
    manifest_data = {
        "title": "Test Episode",
        "topic": "Test Episode",
        "target_duration_seconds": target_duration_seconds,
        "segments": segments or [
            {"number": 1, "title": "Seg", "duration": 60.0, "status": "complete"},
        ],
    }
    if visual_style:
        manifest_data["visual_style"] = visual_style
    manifest_mod.save_manifest(paths["manifest"], manifest_data)
    if with_final:
        final_path = os.path.join(paths["final"], f"{slug}.mp4")
        with open(final_path, "wb") as f:
            f.write(b"fake-mp4-bytes")
    return paths


def test_no_host_path_when_host_output_dir_unset(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "OUTPUT_DIR", str(tmp_path))
    monkeypatch.setattr(api, "HOST_OUTPUT_DIR", "")
    _make_episode(tmp_path)

    progress = api._episode_progress("test-episode")

    assert progress["final_video_exists"] is True
    assert progress["final_video_host_path"] is None


def test_host_path_computed_when_host_output_dir_set(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "OUTPUT_DIR", str(tmp_path))
    monkeypatch.setattr(api, "HOST_OUTPUT_DIR", "/srv/apps/history-generator/output")
    _make_episode(tmp_path)

    progress = api._episode_progress("test-episode")

    assert progress["final_video_host_path"] == (
        "/srv/apps/history-generator/output/test-episode/final/test-episode.mp4"
    )


def test_no_host_path_when_video_not_built_yet(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "OUTPUT_DIR", str(tmp_path))
    monkeypatch.setattr(api, "HOST_OUTPUT_DIR", "/srv/apps/history-generator/output")
    _make_episode(tmp_path, with_final=False)

    progress = api._episode_progress("test-episode")

    assert progress["final_video_exists"] is False
    assert progress["final_video_host_path"] is None


def test_target_reached_true_when_narration_meets_target_even_with_pending_segments(tmp_path, monkeypatch):
    # This is the normal, healthy shape for a finished episode: the outline is
    # deliberately over-provisioned, so a trailing "pending" segment (never attempted,
    # target already hit) doesn't mean the episode is still working -- see
    # pipeline.py's outline-sizing buffer and api.py's target_reached field.
    monkeypatch.setattr(api, "OUTPUT_DIR", str(tmp_path))
    _make_episode(tmp_path, target_duration_seconds=60, with_final=False, segments=[
        {"number": 1, "title": "A", "duration": 33.0, "status": "complete"},
        {"number": 2, "title": "B", "duration": 30.0, "status": "complete"},
        {"number": 3, "title": "C", "duration": None, "status": "pending"},
    ])

    progress = api._episode_progress("test-episode")

    assert progress["narration_seconds"] == 63.0
    assert progress["segments_complete"] == 2
    assert progress["segments_total"] == 3
    assert progress["target_reached"] is True


def test_target_reached_false_when_narration_is_short(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "OUTPUT_DIR", str(tmp_path))
    _make_episode(tmp_path, target_duration_seconds=60, with_final=False, segments=[
        {"number": 1, "title": "A", "duration": 20.0, "status": "complete"},
    ])

    progress = api._episode_progress("test-episode")

    assert progress["target_reached"] is False


def _touch(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"bytes")


def test_stage_is_narrating_before_target_is_reached(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "OUTPUT_DIR", str(tmp_path))
    _make_episode(tmp_path, target_duration_seconds=60, with_final=False, segments=[
        {"number": 1, "title": "A", "duration": 20.0, "status": "complete", "video": "video/001.mp4"},
    ])

    progress = api._episode_progress("test-episode")
    assert progress["stage"] == "narrating"


def test_stage_is_generating_images_when_images_style_and_some_segments_lack_images(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "OUTPUT_DIR", str(tmp_path))
    _make_episode(tmp_path, target_duration_seconds=60, with_final=False, visual_style="images", segments=[
        {"number": 1, "title": "A", "duration": 60.0, "status": "complete", "video": "video/001.mp4", "images": ["images/001_00.png"]},
        {"number": 2, "title": "B", "duration": 20.0, "status": "complete", "video": "video/002.mp4"},
    ])

    progress = api._episode_progress("test-episode")
    assert progress["stage"] == "generating_images"
    assert progress["images_ready"] == 1


def test_stage_is_building_segment_videos_once_images_done_but_videos_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "OUTPUT_DIR", str(tmp_path))
    root = str(tmp_path)
    _make_episode(tmp_path, target_duration_seconds=60, with_final=False, visual_style="images", segments=[
        {"number": 1, "title": "A", "duration": 60.0, "status": "complete", "video": "video/001.mp4", "images": ["images/001_00.png"]},
        {"number": 2, "title": "B", "duration": 20.0, "status": "complete", "video": "video/002.mp4", "images": ["images/002_00.png"]},
    ])
    _touch(os.path.join(root, "test-episode", "video/001.mp4"))
    # video/002.mp4 intentionally not built yet

    progress = api._episode_progress("test-episode")
    assert progress["stage"] == "building_segment_videos"
    assert progress["segment_videos_built"] == 1


def test_stage_is_finalizing_once_all_segment_videos_built_but_no_final(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "OUTPUT_DIR", str(tmp_path))
    root = str(tmp_path)
    _make_episode(tmp_path, target_duration_seconds=60, with_final=False, segments=[
        {"number": 1, "title": "A", "duration": 60.0, "status": "complete", "video": "video/001.mp4"},
    ])
    _touch(os.path.join(root, "test-episode", "video/001.mp4"))

    progress = api._episode_progress("test-episode")
    assert progress["stage"] == "finalizing"
    assert progress["segment_videos_built"] == 1


def test_stage_is_complete_once_final_video_exists(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "OUTPUT_DIR", str(tmp_path))
    root = str(tmp_path)
    _make_episode(tmp_path, target_duration_seconds=60, with_final=True, segments=[
        {"number": 1, "title": "A", "duration": 60.0, "status": "complete", "video": "video/001.mp4"},
    ])
    _touch(os.path.join(root, "test-episode", "video/001.mp4"))

    progress = api._episode_progress("test-episode")
    assert progress["stage"] == "complete"
