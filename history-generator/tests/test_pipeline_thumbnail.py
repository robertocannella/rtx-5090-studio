import os
from types import SimpleNamespace

import manifest as manifest_mod
import pipeline


def _episode(tmp_path):
    paths = manifest_mod.episode_paths(str(tmp_path), "thumbnail-pipeline-test")
    manifest_mod.ensure_dirs(paths)
    m = {"title": "The Episode Title", "segments": []}
    return paths, m


def _ns(visual_style, force=False):
    return SimpleNamespace(
        visual_style=visual_style, force=force,
        ollama_url="http://ollama", model="qwen3:32b", comfyui_url="http://comfyui",
    )


def _fake_generate(monkeypatch, rel_path="images/thumbnail.png", scene="a vivid scene"):
    calls = []

    def fake(ollama_url, model, comfyui_url, domain, topic, title, paths):
        calls.append((topic, title))
        return rel_path, scene

    monkeypatch.setattr(pipeline.episode_thumbnail, "generate", fake)
    return calls


def _fake_free_memory(monkeypatch):
    calls = []
    monkeypatch.setattr(pipeline.image_client, "free_memory", lambda base_url: calls.append(base_url))
    return calls


def test_noop_when_visual_style_is_not_thumbnail(tmp_path, monkeypatch):
    paths, m = _episode(tmp_path)
    calls = _fake_generate(monkeypatch)

    pipeline.apply_thumbnail_to_episode(_ns("static"), paths, m, "Topic", "history")

    assert calls == []
    assert "thumbnail_image" not in m


def test_thumbnail_style_generates_and_caches(tmp_path, monkeypatch):
    paths, m = _episode(tmp_path)
    calls = _fake_generate(monkeypatch)
    free_calls = _fake_free_memory(monkeypatch)

    pipeline.apply_thumbnail_to_episode(_ns("thumbnail"), paths, m, "Topic", "history")

    assert calls == [("Topic", "The Episode Title")]
    assert m["thumbnail_image"] == "images/thumbnail.png"
    assert m["thumbnail_prompt"] == "a vivid scene"
    assert free_calls == ["http://comfyui"]


def test_thumbnail_style_reuses_cached_image_on_resume(tmp_path, monkeypatch):
    paths, m = _episode(tmp_path)
    m["thumbnail_image"] = "images/thumbnail.png"
    m["thumbnail_prompt"] = "already generated"
    calls = _fake_generate(monkeypatch)

    pipeline.apply_thumbnail_to_episode(_ns("thumbnail"), paths, m, "Topic", "history")

    assert calls == []  # cached -- never re-asks Ollama/ComfyUI just because the style is still "thumbnail"
    assert m["thumbnail_prompt"] == "already generated"


def test_thumbnail_style_regenerates_with_force(tmp_path, monkeypatch):
    paths, m = _episode(tmp_path)
    m["thumbnail_image"] = "images/thumbnail.png"
    m["thumbnail_prompt"] = "stale scene"
    calls = _fake_generate(monkeypatch, scene="fresh scene")
    _fake_free_memory(monkeypatch)

    pipeline.apply_thumbnail_to_episode(_ns("thumbnail", force=True), paths, m, "Topic", "history")

    assert calls == [("Topic", "The Episode Title")]
    assert m["thumbnail_prompt"] == "fresh scene"


def test_thumbnail_survives_toggling_visual_style_away_and_back(tmp_path, monkeypatch):
    """Same one-time-choice philosophy as math_visual's select_visual -- once generated,
    switching visual_style away and back again must not burn a second Ollama/ComfyUI call."""
    paths, m = _episode(tmp_path)
    calls = _fake_generate(monkeypatch)
    _fake_free_memory(monkeypatch)

    pipeline.apply_thumbnail_to_episode(_ns("thumbnail"), paths, m, "Topic", "history")
    pipeline.apply_thumbnail_to_episode(_ns("static"), paths, m, "Topic", "history")
    pipeline.apply_thumbnail_to_episode(_ns("thumbnail"), paths, m, "Topic", "history")

    assert len(calls) == 1
