import os

import episode_thumbnail
import manifest as manifest_mod
import pytest


@pytest.fixture
def paths(tmp_path):
    p = manifest_mod.episode_paths(str(tmp_path / "output"), "thumbnail-test")
    manifest_mod.ensure_dirs(p)
    return p


def test_generate_writes_the_image_and_returns_relative_path(paths, monkeypatch):
    calls = []

    def fake_generate_image(comfyui_url, prompt, negative_prompt, width, height):
        calls.append((comfyui_url, prompt, width, height))
        return b"PNGDATA"

    monkeypatch.setattr(episode_thumbnail.image_client, "generate_image", fake_generate_image)
    monkeypatch.setattr(
        episode_thumbnail.ollama_client, "chat_tool",
        lambda *a, **k: {"prompt": "a grand Roman forum at sunset"},
    )

    rel_path, scene = episode_thumbnail.generate(
        "http://ollama", "qwen3:32b", "http://comfyui", "history", "Ancient Rome", "Echoes of Rome", paths,
    )

    assert rel_path == "images/thumbnail.png"
    assert scene == "a grand Roman forum at sunset"
    out_path = os.path.join(paths["root"], rel_path)
    assert os.path.exists(out_path)
    with open(out_path, "rb") as f:
        assert f.read() == b"PNGDATA"
    assert calls[0][0] == "http://comfyui"
    assert "a grand Roman forum at sunset" in calls[0][1]
    assert calls[0][2] == episode_thumbnail.IMAGE_WIDTH
    assert calls[0][3] == episode_thumbnail.IMAGE_HEIGHT


def test_generate_falls_back_to_title_when_ollama_fails(paths, monkeypatch):
    monkeypatch.setattr(episode_thumbnail.image_client, "generate_image", lambda *a, **k: b"PNGDATA")

    def boom(*a, **k):
        raise RuntimeError("ollama unreachable")

    monkeypatch.setattr(episode_thumbnail.ollama_client, "chat_tool", boom)

    rel_path, scene = episode_thumbnail.generate(
        "http://ollama", "qwen3:32b", "http://comfyui", "history", "Ancient Rome", "Echoes of Rome", paths,
    )

    assert scene == "Echoes of Rome"  # falls back to the episode title, not the raw topic
    assert rel_path == "images/thumbnail.png"
