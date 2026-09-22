import pytest

import youtube_publish


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, text=""):
        self.status_code = status_code
        self._json = json_data or {}
        self.text = text or str(json_data)

    def json(self):
        return self._json


class FakeRequests:
    def __init__(self, post_response=None, get_response=None, put_response=None):
        self.post_response = post_response
        self.get_response = get_response
        self.put_response = put_response
        self.post_calls = []
        self.get_calls = []
        self.put_calls = []

    def post(self, url, data=None, timeout=None):
        self.post_calls.append((url, data))
        return self.post_response

    def get(self, url, headers=None, params=None, timeout=None):
        self.get_calls.append((url, headers, params))
        return self.get_response

    def put(self, url, headers=None, params=None, json=None, timeout=None):
        self.put_calls.append((url, headers, params, json))
        return self.put_response


def test_get_access_token_success(monkeypatch):
    fake = FakeRequests(post_response=FakeResponse(200, {"access_token": "abc123"}))
    monkeypatch.setattr(youtube_publish, "requests", fake)

    token = youtube_publish.get_access_token("cid", "secret", "refresh")

    assert token == "abc123"
    assert fake.post_calls[0][1]["grant_type"] == "refresh_token"
    assert fake.post_calls[0][1]["refresh_token"] == "refresh"


def test_get_access_token_raises_on_http_error(monkeypatch):
    fake = FakeRequests(post_response=FakeResponse(400, {"error": "invalid_grant"}))
    monkeypatch.setattr(youtube_publish, "requests", fake)

    with pytest.raises(youtube_publish.YoutubePublishError):
        youtube_publish.get_access_token("cid", "secret", "refresh")


def test_get_access_token_raises_when_token_missing(monkeypatch):
    fake = FakeRequests(post_response=FakeResponse(200, {}))
    monkeypatch.setattr(youtube_publish, "requests", fake)

    with pytest.raises(youtube_publish.YoutubePublishError):
        youtube_publish.get_access_token("cid", "secret", "refresh")


def test_get_video_snippet_returns_snippet(monkeypatch):
    fake = FakeRequests(get_response=FakeResponse(200, {"items": [{"snippet": {"title": "Old Title"}}]}))
    monkeypatch.setattr(youtube_publish, "requests", fake)

    snippet = youtube_publish.get_video_snippet("token", "vid123")

    assert snippet == {"title": "Old Title"}
    assert fake.get_calls[0][2] == {"part": "snippet", "id": "vid123"}


def test_get_video_snippet_raises_when_not_found(monkeypatch):
    fake = FakeRequests(get_response=FakeResponse(200, {"items": []}))
    monkeypatch.setattr(youtube_publish, "requests", fake)

    with pytest.raises(youtube_publish.YoutubePublishError):
        youtube_publish.get_video_snippet("token", "vid123")


def test_update_video_metadata_merges_snippet_and_appends_chapters(monkeypatch):
    fake = FakeRequests(
        post_response=FakeResponse(200, {"access_token": "tok"}),
        get_response=FakeResponse(200, {"items": [{"snippet": {
            "title": "Old", "description": "Old desc", "defaultLanguage": "en",
        }}]}),
        put_response=FakeResponse(200, {"id": "vid123"}),
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
    put_url, put_headers, put_params, put_json = fake.put_calls[0]
    sent_snippet = put_json["snippet"]
    assert sent_snippet["title"] == "New Title"
    assert sent_snippet["description"] == "New description.\n\n0:00 Intro\n1:00 Middle"
    assert sent_snippet["tags"] == ["a", "b"]
    assert sent_snippet["categoryId"] == "28"
    assert sent_snippet["defaultLanguage"] == "en"  # preserved from the fetched snippet, not clobbered
    assert put_headers["Authorization"] == "Bearer tok"
    assert put_json["id"] == "vid123"


def test_update_video_metadata_unknown_category_falls_back_to_default(monkeypatch):
    fake = FakeRequests(
        post_response=FakeResponse(200, {"access_token": "tok"}),
        get_response=FakeResponse(200, {"items": [{"snippet": {}}]}),
        put_response=FakeResponse(200, {}),
    )
    monkeypatch.setattr(youtube_publish, "requests", fake)

    metadata = {"title": "T", "description": "D", "tags": [], "category": "Unknown Category"}
    youtube_publish.update_video_metadata("cid", "secret", "refresh", "vid123", metadata)

    assert fake.put_calls[0][3]["snippet"]["categoryId"] == youtube_publish.DEFAULT_CATEGORY_ID


def test_update_video_metadata_raises_on_put_failure(monkeypatch):
    fake = FakeRequests(
        post_response=FakeResponse(200, {"access_token": "tok"}),
        get_response=FakeResponse(200, {"items": [{"snippet": {}}]}),
        put_response=FakeResponse(403, {"error": "forbidden"}),
    )
    monkeypatch.setattr(youtube_publish, "requests", fake)

    metadata = {"title": "T", "description": "D", "tags": [], "category": "Education"}
    with pytest.raises(youtube_publish.YoutubePublishError):
        youtube_publish.update_video_metadata("cid", "secret", "refresh", "vid123", metadata)
