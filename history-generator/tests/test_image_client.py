import pytest

import image_client


class FakeResponse:
    def __init__(self, json_data=None, content=b"", status_code=200):
        self._json = json_data
        self.content = content
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._json


class FakeRequests:
    """Stands in for the whole `requests` module as seen by image_client -- swapped in
    wholesale via monkeypatch.setattr(image_client, "requests", ...) rather than patching
    individual functions on the real, globally-shared `requests` module.
    """

    def __init__(self, post_responses=None, get_responses=None):
        self.post_responses = list(post_responses or [])
        self.get_responses = list(get_responses or [])
        self.post_calls = []
        self.get_calls = []

    def post(self, url, json=None, timeout=None):
        self.post_calls.append((url, json))
        return self.post_responses.pop(0)

    def get(self, url, params=None, timeout=None):
        self.get_calls.append((url, params))
        # Once only one response remains, keep returning it (simulates polling a
        # not-yet-complete job indefinitely, or a job that never completes).
        if len(self.get_responses) > 1:
            return self.get_responses.pop(0)
        return self.get_responses[0]


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(image_client.time, "sleep", lambda s: None)


def test_generate_image_success(monkeypatch):
    prompt_id = "abc123"
    fake = FakeRequests(
        post_responses=[FakeResponse({"prompt_id": prompt_id, "node_errors": {}})],
        get_responses=[
            FakeResponse({prompt_id: {
                "status": {"completed": True},
                "outputs": {"9": {"images": [{"filename": "out.png", "subfolder": "", "type": "output"}]}},
            }}),
            FakeResponse(content=b"PNGDATA"),
        ],
    )
    monkeypatch.setattr(image_client, "requests", fake)

    result = image_client.generate_image("http://comfyui:8188", "a cat", "text", 1024, 576, seed=1)

    assert result == b"PNGDATA"
    assert fake.post_calls[0][0] == "http://comfyui:8188/prompt"
    workflow = fake.post_calls[0][1]["prompt"]
    assert workflow["4"]["inputs"]["text"] == "a cat"
    assert workflow["5"]["inputs"]["text"] == "text"
    assert workflow["7"]["inputs"]["seed"] == 1
    assert workflow["1"]["inputs"]["unet_name"] == image_client.UNET_NAME


def test_generate_image_node_errors_retries_then_raises(monkeypatch):
    fake = FakeRequests(
        post_responses=[
            FakeResponse({"prompt_id": "x", "node_errors": {"1": "bad field"}}),
            FakeResponse({"prompt_id": "x", "node_errors": {"1": "bad field"}}),
        ],
    )
    monkeypatch.setattr(image_client, "requests", fake)

    with pytest.raises(image_client.ImageError):
        image_client.generate_image("http://comfyui:8188", "x", retries=2, backoff=0)

    assert len(fake.post_calls) == 2


def test_generate_image_job_error_status_raises(monkeypatch):
    prompt_id = "abc"
    fake = FakeRequests(
        post_responses=[FakeResponse({"prompt_id": prompt_id, "node_errors": {}})],
        get_responses=[FakeResponse({prompt_id: {"status": {"completed": False, "status_str": "error"}}})],
    )
    monkeypatch.setattr(image_client, "requests", fake)

    with pytest.raises(image_client.ImageError):
        image_client.generate_image("http://comfyui:8188", "x", retries=1)


def test_generate_image_no_output_images_raises(monkeypatch):
    prompt_id = "abc"
    fake = FakeRequests(
        post_responses=[FakeResponse({"prompt_id": prompt_id, "node_errors": {}})],
        get_responses=[FakeResponse({prompt_id: {"status": {"completed": True}, "outputs": {}}})],
    )
    monkeypatch.setattr(image_client, "requests", fake)

    with pytest.raises(image_client.ImageError):
        image_client.generate_image("http://comfyui:8188", "x", retries=1)


def test_generate_image_times_out_when_job_never_completes(monkeypatch):
    fake = FakeRequests(
        post_responses=[FakeResponse({"prompt_id": "abc", "node_errors": {}})],
        get_responses=[FakeResponse({})],
    )
    monkeypatch.setattr(image_client, "requests", fake)

    with pytest.raises(image_client.ImageError):
        image_client.generate_image("http://comfyui:8188", "x", retries=1, timeout=0.01, poll_interval=0.001)


def test_free_memory_posts_expected_payload(monkeypatch):
    fake = FakeRequests(post_responses=[FakeResponse({})])
    monkeypatch.setattr(image_client, "requests", fake)

    image_client.free_memory("http://comfyui:8188")

    assert fake.post_calls == [
        ("http://comfyui:8188/free", {"unload_models": True, "free_memory": True}),
    ]


def test_free_memory_never_raises_on_failure(monkeypatch, capsys):
    class FailingRequests:
        def post(self, url, json=None, timeout=None):
            raise RuntimeError("comfyui unreachable")

    monkeypatch.setattr(image_client, "requests", FailingRequests())

    image_client.free_memory("http://comfyui:8188")  # must not raise

    assert "non-fatal" in capsys.readouterr().out
