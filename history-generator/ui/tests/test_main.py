import httpx
import pytest
from fastapi.testclient import TestClient

import main


class _FakeResponse:
    def __init__(self, status_code, json_data):
        self.status_code = status_code
        self._json = json_data
        self.text = str(json_data)

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=None, response=self)


class _FakeBinaryResponse:
    def __init__(self, status_code, content, content_type="audio/mpeg"):
        self.status_code = status_code
        self.content = content
        self.headers = {"content-type": content_type}
        self.text = ""

    def json(self):
        raise ValueError("not json")


@pytest.fixture
def client():
    return TestClient(main.app)


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_create_job_proxies_to_history_api(client, monkeypatch):
    captured = {}

    async def fake_request(self, method, url, **kwargs):
        captured["method"] = method
        captured["url"] = url
        captured["json"] = kwargs.get("json")
        return _FakeResponse(202, {"job_id": "abc123", "slug": "test-topic", "status": "started"})

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)

    resp = client.post("/api/jobs", json={"topic": "Test Topic", "domain": "history"})
    assert resp.status_code == 202
    assert resp.json()["job_id"] == "abc123"
    assert captured["method"] == "POST"
    assert captured["url"] == f"{main.HISTORY_API_URL}/jobs"


def test_generate_youtube_metadata_proxies_to_history_api(client, monkeypatch):
    captured = {}

    async def fake_request(self, method, url, **kwargs):
        captured["method"] = method
        captured["url"] = url
        captured["json"] = kwargs.get("json")
        return _FakeResponse(200, {"title": "T"})

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)

    resp = client.post("/api/episodes/some-slug/youtube/generate", json={"force": True})
    assert resp.status_code == 200
    assert captured["method"] == "POST"
    assert captured["url"] == f"{main.HISTORY_API_URL}/episodes/some-slug/youtube/generate"
    assert captured["json"] == {"force": True}


def test_generate_youtube_metadata_proxies_with_empty_body(client, monkeypatch):
    captured = {}

    async def fake_request(self, method, url, **kwargs):
        captured["json"] = kwargs.get("json")
        return _FakeResponse(200, {"title": "T"})

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)

    resp = client.post("/api/episodes/some-slug/youtube/generate")
    assert resp.status_code == 200
    assert captured["json"] == {}


def test_publish_youtube_metadata_proxies_to_history_api(client, monkeypatch):
    captured = {}

    async def fake_request(self, method, url, **kwargs):
        captured["method"] = method
        captured["url"] = url
        captured["json"] = kwargs.get("json")
        return _FakeResponse(200, {"status": "published", "video_id": "vid123"})

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)

    resp = client.post("/api/episodes/some-slug/youtube/publish", json={"video_id": "vid123"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "published"
    assert captured["method"] == "POST"
    assert captured["url"] == f"{main.HISTORY_API_URL}/episodes/some-slug/youtube/publish"
    assert captured["json"] == {"video_id": "vid123"}


def test_create_job_surfaces_validation_errors_verbatim(client, monkeypatch):
    async def fake_request(self, method, url, **kwargs):
        return _FakeResponse(422, {"detail": [{"loc": ["body", "domain"], "msg": "invalid domain"}]})

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)

    resp = client.post("/api/jobs", json={"topic": "x", "domain": "nonsense"})
    assert resp.status_code == 422
    assert "invalid domain" in str(resp.json())


def test_get_job_proxies_to_the_right_path(client, monkeypatch):
    async def fake_request(self, method, url, **kwargs):
        assert method == "GET"
        assert url == f"{main.HISTORY_API_URL}/jobs/xyz"
        return _FakeResponse(200, {"job_id": "xyz", "status": "running"})

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)
    resp = client.get("/api/jobs/xyz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "running"


def test_list_jobs_and_episodes_proxy_to_the_right_paths(client, monkeypatch):
    seen_urls = []

    async def fake_request(self, method, url, **kwargs):
        seen_urls.append(url)
        return _FakeResponse(200, [])

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)
    client.get("/api/jobs")
    client.get("/api/episodes")
    client.get("/api/episodes/some-slug")
    client.get("/api/episodes/some-slug/youtube")
    assert seen_urls == [
        f"{main.HISTORY_API_URL}/jobs",
        f"{main.HISTORY_API_URL}/episodes",
        f"{main.HISTORY_API_URL}/episodes/some-slug",
        f"{main.HISTORY_API_URL}/episodes/some-slug/youtube",
    ]


def test_metadata_proxies(client, monkeypatch):
    async def fake_request(self, method, url, **kwargs):
        assert url == f"{main.HISTORY_API_URL}/metadata"
        return _FakeResponse(200, {"domains": ["history", "math", "discovery"]})

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)
    resp = client.get("/api/metadata")
    assert resp.status_code == 200
    assert "math" in resp.json()["domains"]


def test_upstream_unreachable_returns_502_not_a_crash(client, monkeypatch):
    async def fake_request(self, method, url, **kwargs):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)
    resp = client.get("/api/jobs")
    assert resp.status_code == 502


def test_voices_simplifies_and_sorts_kokoro_response(client, monkeypatch):
    async def fake_get(self, url, **kwargs):
        assert url == f"{main.KOKORO_URL}/v1/audio/voices"
        return _FakeResponse(200, {"voices": [
            {"id": "am_adam", "overall_grade": "F+"},
            {"id": "af_heart", "overall_grade": "A"},
        ]})

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    resp = client.get("/api/voices")
    assert resp.status_code == 200
    ids = [v["id"] for v in resp.json()["voices"]]
    assert ids == ["af_heart", "am_adam"]  # sorted, not upstream order


def test_voices_degrades_gracefully_when_kokoro_unreachable(client, monkeypatch):
    async def fake_get(self, url, **kwargs):
        raise httpx.ConnectError("no route")

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    resp = client.get("/api/voices")
    assert resp.status_code == 200
    assert resp.json() == {"voices": []}


def test_static_index_served_at_root(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Episode Generator" in resp.text


def test_voice_sample_streams_binary_audio_through(client, monkeypatch):
    fake_bytes = b"\x00\x01\x02fake-mp3-bytes"

    async def fake_get(self, url, **kwargs):
        assert url == f"{main.HISTORY_API_URL}/voices/af_heart/sample"
        return _FakeBinaryResponse(200, fake_bytes)

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    resp = client.get("/api/voices/af_heart/sample")
    assert resp.status_code == 200
    assert resp.content == fake_bytes
    assert resp.headers["content-type"] == "audio/mpeg"


def test_voice_sample_404_passthrough_for_unknown_voice(client, monkeypatch):
    async def fake_get(self, url, **kwargs):
        return _FakeBinaryResponse(404, b"", content_type="application/json")

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    resp = client.get("/api/voices/not-a-real-voice/sample")
    assert resp.status_code == 404


def test_voice_sample_502_when_upstream_unreachable(client, monkeypatch):
    async def fake_get(self, url, **kwargs):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    resp = client.get("/api/voices/af_heart/sample")
    assert resp.status_code == 502
