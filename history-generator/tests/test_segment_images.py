import os

import manifest as manifest_mod
import pytest
import segment_images


@pytest.fixture
def paths(tmp_path):
    p = manifest_mod.episode_paths(str(tmp_path / "output"), "seg-img-test")
    manifest_mod.ensure_dirs(p)
    return p


@pytest.mark.parametrize("duration,expected", [
    (None, 2),
    (0, 2),
    (10, 2),
    (30, 2),
    (45, 3),
    (1000, 6),
])
def test_images_for_duration_bounds(duration, expected):
    assert segment_images.images_for_duration(duration) == expected


def test_seed_for_is_deterministic_and_distinct_per_index():
    a = segment_images._seed_for("slug", 1, 0)
    b = segment_images._seed_for("slug", 1, 0)
    c = segment_images._seed_for("slug", 1, 1)
    assert a == b
    assert a != c


def test_generate_for_segment_generates_and_reuses_cache(paths, monkeypatch):
    seg = {"number": 1, "title": "Test Segment", "summary": "", "duration": 30.0}
    calls = []

    def fake_generate_image(base_url, prompt, negative_prompt, width, height, seed):
        calls.append((prompt, seed))
        return b"PNGDATA"

    monkeypatch.setattr(segment_images.image_client, "generate_image", fake_generate_image)
    monkeypatch.setattr(
        segment_images.ollama_client, "chat_tool",
        lambda *a, **k: {"prompts": ["scene one", "scene two"]},
    )

    rel_paths, seg_prompts, changed = segment_images.generate_for_segment(
        "http://ollama", "qwen3:32b", "http://comfyui", "history", seg, "script text", "seg-img-test", paths,
    )

    assert changed is True
    assert len(rel_paths) == 2
    assert len(calls) == 2
    for rel in rel_paths:
        assert os.path.exists(os.path.join(paths["root"], rel))

    seg["images"] = rel_paths
    seg["image_prompts"] = seg_prompts

    # Resuming with the same segment state must not call ComfyUI again.
    rel_paths2, seg_prompts2, changed2 = segment_images.generate_for_segment(
        "http://ollama", "qwen3:32b", "http://comfyui", "history", seg, "script text", "seg-img-test", paths,
    )
    assert changed2 is False
    assert rel_paths2 == rel_paths
    assert seg_prompts2 == seg_prompts
    assert len(calls) == 2  # unchanged -- no new generation happened


def test_generate_for_segment_force_regenerates(paths, monkeypatch):
    seg = {"number": 2, "title": "Test Segment 2", "summary": "", "duration": 30.0}
    calls = []
    monkeypatch.setattr(
        segment_images.image_client, "generate_image",
        lambda *a, **k: (calls.append(1), b"PNGDATA")[1],
    )
    monkeypatch.setattr(segment_images.ollama_client, "chat_tool", lambda *a, **k: {"prompts": ["a", "b"]})

    rel_paths, seg_prompts, changed = segment_images.generate_for_segment(
        "http://ollama", "qwen3:32b", "http://comfyui", "history", seg, "script", "seg-img-test", paths,
    )
    seg["images"] = rel_paths
    seg["image_prompts"] = seg_prompts
    assert len(calls) == 2

    rel_paths2, _, changed2 = segment_images.generate_for_segment(
        "http://ollama", "qwen3:32b", "http://comfyui", "history", seg, "script", "seg-img-test", paths,
        force=True,
    )
    assert changed2 is True
    assert len(calls) == 4


def test_generate_for_segment_regenerates_when_a_cached_file_is_missing(paths, monkeypatch):
    seg = {"number": 3, "title": "T3", "summary": "", "duration": 30.0}
    monkeypatch.setattr(segment_images.image_client, "generate_image", lambda *a, **k: b"PNGDATA")
    monkeypatch.setattr(segment_images.ollama_client, "chat_tool", lambda *a, **k: {"prompts": ["a", "b"]})

    rel_paths, seg_prompts, _ = segment_images.generate_for_segment(
        "http://ollama", "qwen3:32b", "http://comfyui", "history", seg, "script", "seg-img-test", paths,
    )
    seg["images"] = rel_paths
    seg["image_prompts"] = seg_prompts

    os.remove(os.path.join(paths["root"], rel_paths[0]))

    _, _, changed = segment_images.generate_for_segment(
        "http://ollama", "qwen3:32b", "http://comfyui", "history", seg, "script", "seg-img-test", paths,
    )
    assert changed is True


def test_generate_for_segment_falls_back_to_title_when_ollama_fails(paths, monkeypatch):
    seg = {"number": 4, "title": "Fallback Title", "summary": "", "duration": 30.0}
    monkeypatch.setattr(segment_images.image_client, "generate_image", lambda *a, **k: b"PNGDATA")

    def boom(*a, **k):
        raise RuntimeError("ollama unreachable")

    monkeypatch.setattr(segment_images.ollama_client, "chat_tool", boom)

    rel_paths, seg_prompts, changed = segment_images.generate_for_segment(
        "http://ollama", "qwen3:32b", "http://comfyui", "history", seg, "script", "seg-img-test", paths,
    )
    assert changed is True
    assert len(rel_paths) == 2
    assert all("Fallback Title" in p for p in seg_prompts)
