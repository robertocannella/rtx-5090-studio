import os

import api
import manifest as manifest_mod


def _make_episode(tmp_path, slug="test-episode", with_final=True):
    paths = manifest_mod.episode_paths(str(tmp_path), slug)
    manifest_mod.ensure_dirs(paths)
    manifest_mod.save_manifest(paths["manifest"], {
        "title": "Test Episode",
        "topic": "Test Episode",
        "target_duration_seconds": 60,
        "segments": [
            {"number": 1, "title": "Seg", "duration": 60.0, "status": "complete"},
        ],
    })
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
