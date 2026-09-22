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


def test_generate_youtube_metadata_success(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "OUTPUT_DIR", str(tmp_path))
    _make_episode(tmp_path)
    fake_result = {"title": "T", "description": "D", "tags": [], "tags_joined": "", "category": "Education", "chapters": "", "generated_for_segment_count": 1}
    calls = []
    monkeypatch.setattr(
        api.youtube_metadata, "generate",
        lambda *a, **k: calls.append((a, k)) or fake_result,
    )

    result = api.generate_youtube_metadata("test-episode", api.GenerateYoutubeRequest())

    assert result == fake_result
    saved = manifest_mod.load_manifest(manifest_mod.episode_paths(str(tmp_path), "test-episode")["manifest"])
    assert saved["youtube"] == fake_result
    assert calls[0][1]["force"] is False


def test_generate_youtube_metadata_force_is_threaded_through(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "OUTPUT_DIR", str(tmp_path))
    _make_episode(tmp_path)
    calls = []
    monkeypatch.setattr(
        api.youtube_metadata, "generate",
        lambda *a, **k: calls.append(k) or {"title": "T", "description": "D", "tags": [], "category": "Education", "chapters": "", "generated_for_segment_count": 1},
    )

    api.generate_youtube_metadata("test-episode", api.GenerateYoutubeRequest(force=True))

    assert calls[0]["force"] is True


def test_generate_youtube_metadata_404_when_episode_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "OUTPUT_DIR", str(tmp_path))

    with pytest.raises(HTTPException) as exc_info:
        api.generate_youtube_metadata("does-not-exist", api.GenerateYoutubeRequest())
    assert exc_info.value.status_code == 404


def test_generate_youtube_metadata_502_when_generation_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "OUTPUT_DIR", str(tmp_path))
    _make_episode(tmp_path)
    monkeypatch.setattr(api.youtube_metadata, "generate", lambda *a, **k: None)

    with pytest.raises(HTTPException) as exc_info:
        api.generate_youtube_metadata("test-episode", api.GenerateYoutubeRequest())
    assert exc_info.value.status_code == 502


def _configure_youtube_env(monkeypatch, configured=True):
    monkeypatch.setattr(api, "YOUTUBE_CLIENT_ID", "cid" if configured else "")
    monkeypatch.setattr(api, "YOUTUBE_CLIENT_SECRET", "secret" if configured else "")
    monkeypatch.setattr(api, "YOUTUBE_REFRESH_TOKEN", "refresh" if configured else "")


def test_publish_returns_503_when_not_configured(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "OUTPUT_DIR", str(tmp_path))
    _configure_youtube_env(monkeypatch, configured=False)
    _make_episode(tmp_path, youtube={"title": "T", "description": "D", "tags": [], "category": "Education", "chapters": ""})

    with pytest.raises(HTTPException) as exc_info:
        api.publish_youtube_metadata("test-episode", api.PublishYoutubeRequest(video_id="vid123"))
    assert exc_info.value.status_code == 503


def test_publish_404_when_no_youtube_metadata_yet(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "OUTPUT_DIR", str(tmp_path))
    _configure_youtube_env(monkeypatch)
    _make_episode(tmp_path)

    with pytest.raises(HTTPException) as exc_info:
        api.publish_youtube_metadata("test-episode", api.PublishYoutubeRequest(video_id="vid123"))
    assert exc_info.value.status_code == 404


def test_publish_success_stores_video_id_and_timestamp(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "OUTPUT_DIR", str(tmp_path))
    _configure_youtube_env(monkeypatch)
    youtube = {"title": "T", "description": "D", "tags": [], "category": "Education", "chapters": ""}
    _make_episode(tmp_path, youtube=youtube)
    calls = []
    monkeypatch.setattr(
        api.youtube_publish, "update_video_metadata",
        lambda *a, **k: calls.append(a) or {"id": "vid123"},
    )

    result = api.publish_youtube_metadata("test-episode", api.PublishYoutubeRequest(video_id="vid123"))

    assert result == {"status": "published", "video_id": "vid123"}
    # Compare individual args rather than the whole tuple -- the youtube dict passed in
    # is the same object publish_youtube_metadata mutates immediately afterward (adding
    # video_id/published_at), so a captured reference to it reflects that later state too.
    call_args = calls[0]
    assert call_args[:4] == ("cid", "secret", "refresh", "vid123")
    assert call_args[4]["title"] == "T"

    paths = manifest_mod.episode_paths(str(tmp_path), "test-episode")
    saved = manifest_mod.load_manifest(paths["manifest"])
    assert saved["youtube"]["video_id"] == "vid123"
    assert "published_at" in saved["youtube"]


def test_publish_surfaces_publish_errors_as_502(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "OUTPUT_DIR", str(tmp_path))
    _configure_youtube_env(monkeypatch)
    _make_episode(tmp_path, youtube={"title": "T", "description": "D", "tags": [], "category": "Education", "chapters": ""})

    def boom(*a, **k):
        raise api.youtube_publish.YoutubePublishError("video not found")

    monkeypatch.setattr(api.youtube_publish, "update_video_metadata", boom)

    with pytest.raises(HTTPException) as exc_info:
        api.publish_youtube_metadata("test-episode", api.PublishYoutubeRequest(video_id="vid123"))
    assert exc_info.value.status_code == 502
