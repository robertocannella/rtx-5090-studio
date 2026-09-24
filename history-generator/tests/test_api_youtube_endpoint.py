import os

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


def test_update_youtube_metadata_partial_update_only_changes_given_fields(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "OUTPUT_DIR", str(tmp_path))
    original = {
        "title": "Old Title", "description": "Old desc", "tags": ["a"], "tags_joined": "a",
        "category": "Education", "chapters": "0:00 A", "generated_for_segment_count": 1,
    }
    _make_episode(tmp_path, youtube=original)

    result = api.update_youtube_metadata("test-episode", api.UpdateYoutubeMetadataRequest(title="New Title"))

    assert result["title"] == "New Title"
    assert result["description"] == "Old desc"  # untouched
    assert result["chapters"] == "0:00 A"  # never editable
    assert result["generated_for_segment_count"] == 1  # untouched

    saved = manifest_mod.load_manifest(manifest_mod.episode_paths(str(tmp_path), "test-episode")["manifest"])
    assert saved["youtube"]["title"] == "New Title"


def test_update_youtube_metadata_updates_tags_and_rejoins(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "OUTPUT_DIR", str(tmp_path))
    _make_episode(tmp_path, youtube={"title": "T", "description": "D", "tags": ["old"], "tags_joined": "old", "category": "Education", "chapters": ""})

    result = api.update_youtube_metadata(
        "test-episode", api.UpdateYoutubeMetadataRequest(tags=[" space ", "cosmos", "", "  "]),
    )

    assert result["tags"] == ["space", "cosmos"]  # blank/whitespace-only entries dropped
    assert result["tags_joined"] == "space, cosmos"


def test_update_youtube_metadata_truncates_title_to_youtube_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "OUTPUT_DIR", str(tmp_path))
    _make_episode(tmp_path, youtube={"title": "T", "description": "D", "tags": [], "category": "Education", "chapters": ""})

    long_title = "x" * 150
    result = api.update_youtube_metadata("test-episode", api.UpdateYoutubeMetadataRequest(title=long_title))

    assert len(result["title"]) == 100


def test_update_youtube_metadata_rejects_empty_title(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "OUTPUT_DIR", str(tmp_path))
    _make_episode(tmp_path, youtube={"title": "T", "description": "D", "tags": [], "category": "Education", "chapters": ""})

    with pytest.raises(HTTPException) as exc_info:
        api.update_youtube_metadata("test-episode", api.UpdateYoutubeMetadataRequest(title="   "))
    assert exc_info.value.status_code == 422


def test_update_youtube_metadata_rejects_invalid_category():
    with pytest.raises(Exception):  # pydantic ValidationError at construction time
        api.UpdateYoutubeMetadataRequest(category="Not A Real Category")


def test_update_youtube_metadata_404_when_not_generated_yet(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "OUTPUT_DIR", str(tmp_path))
    _make_episode(tmp_path)

    with pytest.raises(HTTPException) as exc_info:
        api.update_youtube_metadata("test-episode", api.UpdateYoutubeMetadataRequest(title="X"))
    assert exc_info.value.status_code == 404


def test_update_youtube_metadata_404_when_episode_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "OUTPUT_DIR", str(tmp_path))

    with pytest.raises(HTTPException) as exc_info:
        api.update_youtube_metadata("does-not-exist", api.UpdateYoutubeMetadataRequest(title="X"))
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


class ImmediateThread:
    """Runs the target synchronously in .start() instead of on a real thread, so tests
    can assert on the outcome without racing a background thread."""

    def __init__(self, target=None, args=(), kwargs=None, daemon=None):
        self.target = target
        self.args = args
        self.kwargs = kwargs or {}

    def start(self):
        self.target(*self.args, **self.kwargs)


def _touch(path, content=b"fake mp4 bytes"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(content)


def test_publish_without_video_id_uploads_and_stores_result(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "OUTPUT_DIR", str(tmp_path))
    monkeypatch.setattr(api, "threading", type("T", (), {"Thread": ImmediateThread}))
    _configure_youtube_env(monkeypatch)
    api._youtube_publish_status.clear()
    youtube = {"title": "T", "description": "D", "tags": [], "category": "Education", "chapters": ""}
    _make_episode(tmp_path, youtube=youtube)
    paths = manifest_mod.episode_paths(str(tmp_path), "test-episode")
    _touch(os.path.join(paths["final"], "test-episode.mp4"))

    calls = []
    monkeypatch.setattr(
        api.youtube_publish, "upload_video",
        lambda *a, **k: calls.append((a, k)) or {"id": "newvid123"},
    )

    result = api.publish_youtube_metadata("test-episode", api.PublishYoutubeRequest())

    assert result == {"status": "uploading"}
    assert api._youtube_publish_status["test-episode"]["status"] == "complete"
    assert api._youtube_publish_status["test-episode"]["video_id"] == "newvid123"
    assert calls[0][1]["privacy_status"] == "private"  # default, never silently public

    saved = manifest_mod.load_manifest(paths["manifest"])
    assert saved["youtube"]["video_id"] == "newvid123"


def test_publish_without_video_id_honors_explicit_privacy_status(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "OUTPUT_DIR", str(tmp_path))
    monkeypatch.setattr(api, "threading", type("T", (), {"Thread": ImmediateThread}))
    _configure_youtube_env(monkeypatch)
    api._youtube_publish_status.clear()
    _make_episode(tmp_path, youtube={"title": "T", "description": "D", "tags": [], "category": "Education", "chapters": ""})
    paths = manifest_mod.episode_paths(str(tmp_path), "test-episode")
    _touch(os.path.join(paths["final"], "test-episode.mp4"))
    calls = []
    monkeypatch.setattr(api.youtube_publish, "upload_video", lambda *a, **k: calls.append(k) or {"id": "v"})

    api.publish_youtube_metadata("test-episode", api.PublishYoutubeRequest(privacy_status="unlisted"))

    assert calls[0]["privacy_status"] == "unlisted"


def test_publish_without_video_id_rejects_invalid_privacy_status(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "OUTPUT_DIR", str(tmp_path))
    _configure_youtube_env(monkeypatch)
    _make_episode(tmp_path, youtube={"title": "T", "description": "D", "tags": [], "category": "Education", "chapters": ""})
    paths = manifest_mod.episode_paths(str(tmp_path), "test-episode")
    _touch(os.path.join(paths["final"], "test-episode.mp4"))

    with pytest.raises(HTTPException) as exc_info:
        api.publish_youtube_metadata("test-episode", api.PublishYoutubeRequest(privacy_status="super-public"))
    assert exc_info.value.status_code == 422


def test_publish_without_video_id_400_when_final_video_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "OUTPUT_DIR", str(tmp_path))
    _configure_youtube_env(monkeypatch)
    _make_episode(tmp_path, youtube={"title": "T", "description": "D", "tags": [], "category": "Education", "chapters": ""})

    with pytest.raises(HTTPException) as exc_info:
        api.publish_youtube_metadata("test-episode", api.PublishYoutubeRequest())
    assert exc_info.value.status_code == 400


def test_publish_without_video_id_does_not_start_a_second_upload_while_one_is_in_flight(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "OUTPUT_DIR", str(tmp_path))
    _configure_youtube_env(monkeypatch)
    api._youtube_publish_status.clear()
    api._youtube_publish_status["test-episode"] = {"status": "uploading"}
    _make_episode(tmp_path, youtube={"title": "T", "description": "D", "tags": [], "category": "Education", "chapters": ""})
    paths = manifest_mod.episode_paths(str(tmp_path), "test-episode")
    _touch(os.path.join(paths["final"], "test-episode.mp4"))
    calls = []
    monkeypatch.setattr(api.youtube_publish, "upload_video", lambda *a, **k: calls.append(1))

    result = api.publish_youtube_metadata("test-episode", api.PublishYoutubeRequest())

    assert result == {"status": "uploading"}
    assert calls == []  # no new upload actually started


def test_publish_without_video_id_records_error_status_on_upload_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "OUTPUT_DIR", str(tmp_path))
    monkeypatch.setattr(api, "threading", type("T", (), {"Thread": ImmediateThread}))
    _configure_youtube_env(monkeypatch)
    api._youtube_publish_status.clear()
    _make_episode(tmp_path, youtube={"title": "T", "description": "D", "tags": [], "category": "Education", "chapters": ""})
    paths = manifest_mod.episode_paths(str(tmp_path), "test-episode")
    _touch(os.path.join(paths["final"], "test-episode.mp4"))

    def boom(*a, **k):
        raise api.youtube_publish.YoutubePublishError("quota exceeded")

    monkeypatch.setattr(api.youtube_publish, "upload_video", boom)

    api.publish_youtube_metadata("test-episode", api.PublishYoutubeRequest())

    assert api._youtube_publish_status["test-episode"]["status"] == "error"
    assert "quota exceeded" in api._youtube_publish_status["test-episode"]["error"]


def test_get_youtube_publish_status_returns_current_status():
    api._youtube_publish_status["test-episode"] = {"status": "uploading"}
    assert api.get_youtube_publish_status("test-episode") == {"status": "uploading"}


def test_get_youtube_publish_status_404_when_untracked():
    api._youtube_publish_status.pop("never-started", None)
    with pytest.raises(HTTPException) as exc_info:
        api.get_youtube_publish_status("never-started")
    assert exc_info.value.status_code == 404
