import threading

import gpu_lock
import image_client
import ollama_client


class _FakeResponse:
    def __init__(self, data):
        self._data = data
        self.content = b""

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


def test_ollama_and_image_client_share_the_same_lock():
    # Strict sequential GPU scheduling only works if every GPU-bound call site is
    # blocked by the exact same mutex, not one each -- see gpu_lock.py.
    assert ollama_client.gpu_lock is gpu_lock.gpu_lock
    assert image_client.gpu_lock is gpu_lock.gpu_lock


def test_image_client_holds_gpu_lock_during_submit(monkeypatch):
    seen_locked_during_post = []

    class FakeRequests:
        def post(self, url, json=None, timeout=None):
            seen_locked_during_post.append(gpu_lock.gpu_lock.locked())
            return _FakeResponse({"prompt_id": "x", "node_errors": {}})

        def get(self, url, params=None, timeout=None):
            if "history" in url:
                return _FakeResponse({"x": {
                    "status": {"completed": True},
                    "outputs": {"9": {"images": [{"filename": "f.png", "subfolder": "", "type": "output"}]}},
                }})
            resp = _FakeResponse(None)
            resp.content = b"PNG"
            return resp

    monkeypatch.setattr(image_client, "requests", FakeRequests())

    image_client.generate_image("http://comfyui", "a prompt")

    assert seen_locked_during_post == [True]
    assert not gpu_lock.gpu_lock.locked()


def test_gpu_lock_forces_a_second_acquirer_to_wait_while_ollama_call_is_in_flight(monkeypatch):
    release_ollama = threading.Event()
    started = threading.Event()

    class FakeRequests:
        def post(self, url, json=None, timeout=None):
            started.set()
            release_ollama.wait(timeout=5)
            return _FakeResponse({"message": {"content": "{}"}})

    monkeypatch.setattr(ollama_client, "requests", FakeRequests())

    t = threading.Thread(target=lambda: ollama_client.chat_json("http://ollama", "m", "s", "u"))
    t.start()
    assert started.wait(timeout=5)

    # Anything else contending for the GPU (standing in for image_client's own
    # generate_image call) must be forced to wait, not interleave, while Ollama's
    # request is in flight.
    acquired = gpu_lock.gpu_lock.acquire(timeout=0.2)
    try:
        assert acquired is False
    finally:
        if acquired:
            gpu_lock.gpu_lock.release()
        release_ollama.set()
        t.join(timeout=5)

    assert not gpu_lock.gpu_lock.locked()
