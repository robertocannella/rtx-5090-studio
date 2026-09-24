import os

import pytest
from fastapi import HTTPException

import api
import manifest as manifest_mod


def _make_episode(tmp_path, slug="test-episode", title="Original Title"):
    paths = manifest_mod.episode_paths(str(tmp_path), slug)
    manifest_mod.ensure_dirs(paths)
    manifest_mod.save_manifest(paths["manifest"], {
        "title": title,
        "topic": "Test Episode",
        "segments": [{"number": 1, "title": "A", "duration": 60.0, "status": "complete"}],
    })
    return paths


def test_update_episode_renames_title(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "OUTPUT_DIR", str(tmp_path))
    _make_episode(tmp_path)

    result = api.update_episode("test-episode", api.UpdateEpisodeRequest(title="New Title"))

    assert result["title"] == "New Title"
    paths = manifest_mod.episode_paths(str(tmp_path), "test-episode")
    assert manifest_mod.load_manifest(paths["manifest"])["title"] == "New Title"


def test_update_episode_strips_whitespace(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "OUTPUT_DIR", str(tmp_path))
    _make_episode(tmp_path)

    api.update_episode("test-episode", api.UpdateEpisodeRequest(title="  Padded Title  "))

    paths = manifest_mod.episode_paths(str(tmp_path), "test-episode")
    assert manifest_mod.load_manifest(paths["manifest"])["title"] == "Padded Title"


def test_update_episode_rejects_empty_title(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "OUTPUT_DIR", str(tmp_path))
    _make_episode(tmp_path)

    with pytest.raises(HTTPException) as exc_info:
        api.update_episode("test-episode", api.UpdateEpisodeRequest(title="   "))
    assert exc_info.value.status_code == 422


def test_update_episode_404_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "OUTPUT_DIR", str(tmp_path))

    with pytest.raises(HTTPException) as exc_info:
        api.update_episode("does-not-exist", api.UpdateEpisodeRequest(title="X"))
    assert exc_info.value.status_code == 404


def test_delete_episode_removes_the_whole_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "OUTPUT_DIR", str(tmp_path))
    paths = _make_episode(tmp_path)
    assert os.path.isdir(paths["root"])

    result = api.delete_episode("test-episode")

    assert result == {"status": "deleted", "slug": "test-episode"}
    assert not os.path.exists(paths["root"])


def test_delete_episode_404_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "OUTPUT_DIR", str(tmp_path))

    with pytest.raises(HTTPException) as exc_info:
        api.delete_episode("does-not-exist")
    assert exc_info.value.status_code == 404


def test_delete_episode_409_while_job_active(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "OUTPUT_DIR", str(tmp_path))
    _make_episode(tmp_path)
    api._active_slugs["test-episode"] = "some-job-id"
    try:
        with pytest.raises(HTTPException) as exc_info:
            api.delete_episode("test-episode")
        assert exc_info.value.status_code == 409
    finally:
        api._active_slugs.pop("test-episode", None)

    # Refused -- the directory must still be there.
    paths = manifest_mod.episode_paths(str(tmp_path), "test-episode")
    assert os.path.isdir(paths["root"])


def test_delete_episode_clears_tracked_publish_status(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "OUTPUT_DIR", str(tmp_path))
    _make_episode(tmp_path)
    api._youtube_publish_status["test-episode"] = {"status": "complete", "video_id": "v1"}

    api.delete_episode("test-episode")

    assert "test-episode" not in api._youtube_publish_status


def test_safe_episode_root_rejects_path_traversal(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "OUTPUT_DIR", str(tmp_path))
    with pytest.raises(HTTPException) as exc_info:
        api._safe_episode_root("..")
    assert exc_info.value.status_code == 400


def test_safe_episode_root_rejects_nested_traversal(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "OUTPUT_DIR", str(tmp_path))
    with pytest.raises(HTTPException) as exc_info:
        api._safe_episode_root("../../etc")
    assert exc_info.value.status_code == 400


def test_safe_episode_root_accepts_normal_slug(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "OUTPUT_DIR", str(tmp_path))
    paths = api._safe_episode_root("normal-slug")
    assert paths["root"] == os.path.join(str(tmp_path), "normal-slug")
