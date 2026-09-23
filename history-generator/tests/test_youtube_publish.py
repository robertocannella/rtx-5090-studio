import os

import pytest

import youtube_publish


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, text="", headers=None):
        self.status_code = status_code
        self._json = json_data or {}
        self.text = text or str(json_data)
        self.headers = headers or {}

    def json(self):
        return self._json


class FakeRequests:
    """Stands in for the whole `requests` module. post/get/put each pop the next queued
    response in call order -- a single high-level operation here (e.g. upload_video)
    makes several real requests.* calls across different endpoints, so a fixed
    one-response-per-verb fake isn't enough.
    """

    def __init__(self, post_responses=None, get_responses=None, put_responses=None):
        self.post_responses = list(post_responses or [])
        self.get_responses = list(get_responses or [])
        self.put_responses = list(put_responses or [])
        self.post_calls = []
        self.get_calls = []
        self.put_calls = []

    def post(self, url, **kwargs):
        self.post_calls.append((url, kwargs))
        return self.post_responses.pop(0)

    def get(self, url, **kwargs):
        self.get_calls.append((url, kwargs))
        return self.get_responses.pop(0)

    def put(self, url, **kwargs):
        self.put_calls.append((url, kwargs))
        return self.put_responses.pop(0)


def test_get_access_token_success(monkeypatch):
    fake = FakeRequests(post_responses=[FakeResponse(200, {"access_token": "abc123"})])
    monkeypatch.setattr(youtube_publish, "requests", fake)

    token = youtube_publish.get_access_token("cid", "secret", "refresh")

    assert token == "abc123"
    assert fake.post_calls[0][1]["data"]["grant_type"] == "refresh_token"
    assert fake.post_calls[0][1]["data"]["refresh_token"] == "refresh"


def test_get_access_token_raises_on_http_error(monkeypatch):
    fake = FakeRequests(post_responses=[FakeResponse(400, {"error": "invalid_grant"})])
    monkeypatch.setattr(youtube_publish, "requests", fake)

    with pytest.raises(youtube_publish.YoutubePublishError):
        youtube_publish.get_access_token("cid", "secret", "refresh")


def test_get_access_token_raises_when_token_missing(monkeypatch):
    fake = FakeRequests(post_responses=[FakeResponse(200, {})])
    monkeypatch.setattr(youtube_publish, "requests", fake)

    with pytest.raises(youtube_publish.YoutubePublishError):
        youtube_publish.get_access_token("cid", "secret", "refresh")


def test_get_video_snippet_returns_snippet(monkeypatch):
    fake = FakeRequests(get_responses=[FakeResponse(200, {"items": [{"snippet": {"title": "Old Title"}}]})])
    monkeypatch.setattr(youtube_publish, "requests", fake)

    snippet = youtube_publish.get_video_snippet("token", "vid123")

    assert snippet == {"title": "Old Title"}
    assert fake.get_calls[0][1]["params"] == {"part": "snippet", "id": "vid123"}


def test_get_video_snippet_raises_when_not_found(monkeypatch):
    fake = FakeRequests(get_responses=[FakeResponse(200, {"items": []})])
    monkeypatch.setattr(youtube_publish, "requests", fake)

    with pytest.raises(youtube_publish.YoutubePublishError):
        youtube_publish.get_video_snippet("token", "vid123")


def test_snippet_from_metadata_appends_chapters_and_maps_category():
    metadata = {
        "title": "New Title", "description": "New description.", "tags": ["a", "b"],
        "category": "Science & Technology", "chapters": "0:00 Intro\n1:00 Middle",
    }
    snippet = youtube_publish._snippet_from_metadata(metadata)
    assert snippet["title"] == "New Title"
    assert snippet["description"] == "New description.\n\n0:00 Intro\n1:00 Middle"
    assert snippet["tags"] == ["a", "b"]
    assert snippet["categoryId"] == "28"


def test_build_description_returns_combination_unchanged_when_under_limit():
    result = youtube_publish._build_description("Short desc.", "0:00 A\n1:00 B")
    assert result == "Short desc.\n\n0:00 A\n1:00 B"


def test_build_description_no_chapters_just_truncates_description():
    long_desc = "x" * 6000
    result = youtube_publish._build_description(long_desc, "")
    assert len(result) == youtube_publish.YOUTUBE_DESCRIPTION_MAX_CHARS


def test_build_description_truncates_chapters_on_whole_lines_when_over_limit():
    # Regression test for a real failure: a 112-segment (123-minute) episode's chapters
    # list alone was 5403 characters, and YouTube's videos.insert/update reject the
    # whole request with "invalidDescription" once snippet.description exceeds 5000
    # characters -- nothing here truncated it before this fix.
    base_description = "A summary. " * 20  # ~220 chars, leaves plenty of budget to inspect
    chapter_lines = [f"{i}:00 Chapter number {i} with a reasonably descriptive title" for i in range(200)]
    chapters = "\n".join(chapter_lines)
    assert len(base_description) + len(chapters) > youtube_publish.YOUTUBE_DESCRIPTION_MAX_CHARS

    result = youtube_publish._build_description(base_description, chapters)

    assert len(result) <= youtube_publish.YOUTUBE_DESCRIPTION_MAX_CHARS
    assert result.startswith(base_description)
    assert result.endswith(youtube_publish._DESCRIPTION_TRUNCATION_NOTE)
    # Only whole lines were kept -- no line fragment sitting between the last kept
    # chapter and the truncation note.
    body = result[len(base_description) + 2 : -len(youtube_publish._DESCRIPTION_TRUNCATION_NOTE)]
    for line in body.split("\n"):
        assert line in chapter_lines
    # Early chapters are kept, not dropped in favor of later ones.
    assert chapter_lines[0] in body
    assert chapter_lines[-1] not in body


def test_build_description_extremely_long_base_description_drops_chapters_entirely():
    huge_description = "x" * (youtube_publish.YOUTUBE_DESCRIPTION_MAX_CHARS - 10)
    result = youtube_publish._build_description(huge_description, "0:00 A\n1:00 B")
    assert len(result) <= youtube_publish.YOUTUBE_DESCRIPTION_MAX_CHARS
    assert "0:00 A" not in result


def test_update_video_metadata_and_upload_video_stay_under_description_limit(monkeypatch, tmp_path):
    # End-to-end check through both public entry points, not just _build_description
    # directly, since that's what actually protects a real publish call.
    chapters = "\n".join(f"{i}:00 Segment {i}" for i in range(200))
    metadata = {"title": "T", "description": "Summary.", "tags": [], "category": "Education", "chapters": chapters}

    fake = FakeRequests(
        post_responses=[FakeResponse(200, {"access_token": "tok"})],
        get_responses=[FakeResponse(200, {"items": [{"snippet": {}}]})],
        put_responses=[FakeResponse(200, {"id": "vid123"})],
    )
    monkeypatch.setattr(youtube_publish, "requests", fake)
    youtube_publish.update_video_metadata("cid", "secret", "refresh", "vid123", metadata)
    sent_description = fake.put_calls[0][1]["json"]["snippet"]["description"]
    assert len(sent_description) <= youtube_publish.YOUTUBE_DESCRIPTION_MAX_CHARS


def test_snippet_from_metadata_preserves_base_snippet_fields():
    base = {"title": "Old", "description": "Old desc", "defaultLanguage": "en"}
    metadata = {"title": "New", "description": "New", "tags": [], "category": "Education"}
    snippet = youtube_publish._snippet_from_metadata(metadata, base_snippet=base)
    assert snippet["defaultLanguage"] == "en"
    assert snippet["title"] == "New"


def test_snippet_from_metadata_unknown_category_falls_back_to_default():
    metadata = {"title": "T", "description": "D", "tags": [], "category": "Unknown Category"}
    snippet = youtube_publish._snippet_from_metadata(metadata)
    assert snippet["categoryId"] == youtube_publish.DEFAULT_CATEGORY_ID


def test_update_video_metadata_merges_snippet_and_appends_chapters(monkeypatch):
    fake = FakeRequests(
        post_responses=[FakeResponse(200, {"access_token": "tok"})],
        get_responses=[FakeResponse(200, {"items": [{"snippet": {
            "title": "Old", "description": "Old desc", "defaultLanguage": "en",
        }}]})],
        put_responses=[FakeResponse(200, {"id": "vid123"})],
    )
    monkeypatch.setattr(youtube_publish, "requests", fake)

    metadata = {
        "title": "New Title",
        "description": "New description.",
        "tags": ["a", "b"],
        "category": "Science & Technology",
        "chapters": "0:00 Intro\n1:00 Middle",
    }

    result = youtube_publish.update_video_metadata("cid", "secret", "refresh", "vid123", metadata)

    assert result == {"id": "vid123"}
    put_url, put_kwargs = fake.put_calls[0]
    sent_snippet = put_kwargs["json"]["snippet"]
    assert sent_snippet["title"] == "New Title"
    assert sent_snippet["description"] == "New description.\n\n0:00 Intro\n1:00 Middle"
    assert sent_snippet["tags"] == ["a", "b"]
    assert sent_snippet["categoryId"] == "28"
    assert sent_snippet["defaultLanguage"] == "en"  # preserved from the fetched snippet, not clobbered
    assert put_kwargs["headers"]["Authorization"] == "Bearer tok"
    assert put_kwargs["json"]["id"] == "vid123"


def test_update_video_metadata_raises_on_put_failure(monkeypatch):
    fake = FakeRequests(
        post_responses=[FakeResponse(200, {"access_token": "tok"})],
        get_responses=[FakeResponse(200, {"items": [{"snippet": {}}]})],
        put_responses=[FakeResponse(403, {"error": "forbidden"})],
    )
    monkeypatch.setattr(youtube_publish, "requests", fake)

    metadata = {"title": "T", "description": "D", "tags": [], "category": "Education"}
    with pytest.raises(youtube_publish.YoutubePublishError):
        youtube_publish.update_video_metadata("cid", "secret", "refresh", "vid123", metadata)


def test_initiate_resumable_upload_returns_location_header(monkeypatch):
    fake = FakeRequests(post_responses=[FakeResponse(200, {}, headers={"Location": "https://upload.example/session123"})])
    monkeypatch.setattr(youtube_publish, "requests", fake)

    url = youtube_publish.initiate_resumable_upload("tok", {"title": "T"}, {"privacyStatus": "private"}, 12345)

    assert url == "https://upload.example/session123"
    post_url, kwargs = fake.post_calls[0]
    assert post_url == youtube_publish.RESUMABLE_UPLOAD_URL
    assert kwargs["params"] == {"uploadType": "resumable", "part": "snippet,status"}
    assert kwargs["headers"]["X-Upload-Content-Length"] == "12345"
    assert kwargs["headers"]["X-Upload-Content-Type"] == "video/mp4"
    assert kwargs["json"] == {"snippet": {"title": "T"}, "status": {"privacyStatus": "private"}}


def test_initiate_resumable_upload_raises_without_location_header(monkeypatch):
    fake = FakeRequests(post_responses=[FakeResponse(200, {})])
    monkeypatch.setattr(youtube_publish, "requests", fake)

    with pytest.raises(youtube_publish.YoutubePublishError):
        youtube_publish.initiate_resumable_upload("tok", {}, {}, 123)


def test_initiate_resumable_upload_raises_on_http_error(monkeypatch):
    fake = FakeRequests(post_responses=[FakeResponse(400, {"error": "bad request"})])
    monkeypatch.setattr(youtube_publish, "requests", fake)

    with pytest.raises(youtube_publish.YoutubePublishError):
        youtube_publish.initiate_resumable_upload("tok", {}, {}, 123)


def test_upload_video_file_puts_file_bytes(tmp_path, monkeypatch):
    video_path = tmp_path / "episode.mp4"
    video_path.write_bytes(b"fake video bytes")
    fake = FakeRequests(put_responses=[FakeResponse(200, {"id": "newvid123"})])
    monkeypatch.setattr(youtube_publish, "requests", fake)

    result = youtube_publish.upload_video_file("https://upload.example/session123", str(video_path))

    assert result == {"id": "newvid123"}
    put_url, kwargs = fake.put_calls[0]
    assert put_url == "https://upload.example/session123"
    assert kwargs["headers"]["Content-Length"] == str(len(b"fake video bytes"))
    assert kwargs["headers"]["Content-Type"] == "video/mp4"


def test_upload_video_file_raises_on_http_error(tmp_path, monkeypatch):
    video_path = tmp_path / "episode.mp4"
    video_path.write_bytes(b"fake video bytes")
    fake = FakeRequests(put_responses=[FakeResponse(403, {"error": "quota exceeded"})])
    monkeypatch.setattr(youtube_publish, "requests", fake)

    with pytest.raises(youtube_publish.YoutubePublishError):
        youtube_publish.upload_video_file("https://upload.example/session123", str(video_path))


def test_upload_video_full_flow(tmp_path, monkeypatch):
    video_path = tmp_path / "episode.mp4"
    video_path.write_bytes(b"x" * 1000)
    fake = FakeRequests(
        post_responses=[
            FakeResponse(200, {"access_token": "tok"}),
            FakeResponse(200, {}, headers={"Location": "https://upload.example/session123"}),
        ],
        put_responses=[FakeResponse(200, {"id": "newvid123", "snippet": {"title": "T"}})],
    )
    monkeypatch.setattr(youtube_publish, "requests", fake)

    metadata = {"title": "T", "description": "D", "tags": ["a"], "category": "Education", "chapters": ""}
    result = youtube_publish.upload_video("cid", "secret", "refresh", str(video_path), metadata)

    assert result["id"] == "newvid123"
    # status defaults to private -- never silently public.
    initiate_kwargs = fake.post_calls[1][1]
    assert initiate_kwargs["json"]["status"] == {"privacyStatus": "private"}
    assert initiate_kwargs["json"]["snippet"]["title"] == "T"


def test_upload_video_rejects_invalid_privacy_status(tmp_path):
    video_path = tmp_path / "episode.mp4"
    video_path.write_bytes(b"x")
    metadata = {"title": "T", "description": "D", "tags": [], "category": "Education"}

    with pytest.raises(youtube_publish.YoutubePublishError):
        youtube_publish.upload_video("cid", "secret", "refresh", str(video_path), metadata, privacy_status="public-ish")


def test_upload_video_raises_when_file_missing():
    metadata = {"title": "T", "description": "D", "tags": [], "category": "Education"}
    with pytest.raises(youtube_publish.YoutubePublishError):
        youtube_publish.upload_video("cid", "secret", "refresh", "/no/such/file.mp4", metadata)


def test_upload_video_honors_explicit_privacy_status(tmp_path, monkeypatch):
    video_path = tmp_path / "episode.mp4"
    video_path.write_bytes(b"x" * 10)
    fake = FakeRequests(
        post_responses=[
            FakeResponse(200, {"access_token": "tok"}),
            FakeResponse(200, {}, headers={"Location": "https://upload.example/session123"}),
        ],
        put_responses=[FakeResponse(200, {"id": "newvid123"})],
    )
    monkeypatch.setattr(youtube_publish, "requests", fake)

    metadata = {"title": "T", "description": "D", "tags": [], "category": "Education"}
    youtube_publish.upload_video("cid", "secret", "refresh", str(video_path), metadata, privacy_status="unlisted")

    initiate_kwargs = fake.post_calls[1][1]
    assert initiate_kwargs["json"]["status"] == {"privacyStatus": "unlisted"}
