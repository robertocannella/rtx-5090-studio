import pytest
from fastapi import HTTPException

import api
import manifest as manifest_mod


def _make_episode(tmp_path, slug="test-episode", youtube=None):
    paths = manifest_mod.episode_paths(str(tmp_path), slug)
    manifest_mod.ensure_dirs(paths)
    data = {
        "title": "Test Episode",
        "topic": "Test Episode",
        "segments": [{"number": 1, "title": "A", "duration": 60.0, "status": "complete"}],
    }
    if youtube is not None:
        data["youtube"] = youtube
    manifest_mod.save_manifest(paths["manifest"], data)


def test_get_youtube_metadata_returns_stored_data(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "OUTPUT_DIR", str(tmp_path))
    youtube = {"title": "T", "description": "D", "tags": ["a"], "tags_joined": "a", "category": "Education", "chapters": "0:00 A"}
    _make_episode(tmp_path, youtube=youtube)

    result = api.get_youtube_metadata("test-episode")
    assert result == youtube


def test_get_youtube_metadata_404_when_not_generated(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "OUTPUT_DIR", str(tmp_path))
    _make_episode(tmp_path)

    with pytest.raises(HTTPException) as exc_info:
        api.get_youtube_metadata("test-episode")
    assert exc_info.value.status_code == 404


def test_get_youtube_metadata_404_when_episode_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "OUTPUT_DIR", str(tmp_path))

    with pytest.raises(HTTPException) as exc_info:
        api.get_youtube_metadata("does-not-exist")
    assert exc_info.value.status_code == 404
