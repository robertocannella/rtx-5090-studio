import os
from types import SimpleNamespace

import manifest as manifest_mod
import pipeline


def _episode(tmp_path, script_text="Some narration script."):
    paths = manifest_mod.episode_paths(str(tmp_path), "images-pipeline-test")
    manifest_mod.ensure_dirs(paths)
    script_path = os.path.join(paths["root"], "scripts/001.txt")
    os.makedirs(os.path.dirname(script_path), exist_ok=True)
    with open(script_path, "w") as f:
        f.write(script_text)
    m = {
        "segments": [
            {
                "number": 1,
                "title": "Segment One",
                "summary": "",
                "script": "scripts/001.txt",
                "audio": "audio/001.mp3",
                "video": "video/001.mp4",
                "duration": 30.0,
                "status": "complete",
            },
        ],
    }
    return paths, m


def _touch(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"fake-bytes")


def _ns(visual_style, force=False):
    return SimpleNamespace(
        visual_style=visual_style, force=force,
        ollama_url="http://ollama", model="qwen3:32b", comfyui_url="http://comfyui",
    )


def _fake_generate_for_segment(monkeypatch, images=("images/001_00.png", "images/001_01.png"), prompts=("a", "b"), changed=True):
    calls = []

    def fake(ollama_url, model, comfyui_url, domain, seg, script_text, slug, paths, force=False):
        calls.append((seg["number"], force))
        for rel in images:
            full = os.path.join(paths["root"], rel)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "wb") as f:
                f.write(b"png")
        return list(images), list(prompts), changed

    monkeypatch.setattr(pipeline.segment_images, "generate_for_segment", fake)
    return calls


def test_noop_when_visual_style_is_not_images(tmp_path, monkeypatch):
    paths, m = _episode(tmp_path)
    calls = _fake_generate_for_segment(monkeypatch)

    pipeline.apply_images_to_segments(_ns("static"), paths, m, "Topic", "history", "images-pipeline-test")

    assert calls == []
    assert "images" not in m["segments"][0]


def test_images_style_generates_and_invalidates_stale_video(tmp_path, monkeypatch):
    paths, m = _episode(tmp_path)
    video_path = os.path.join(paths["root"], m["segments"][0]["video"])
    _touch(video_path)
    _fake_generate_for_segment(monkeypatch, changed=True)

    pipeline.apply_images_to_segments(_ns("images"), paths, m, "Topic", "history", "images-pipeline-test")

    seg = m["segments"][0]
    assert seg["images"] == ["images/001_00.png", "images/001_01.png"]
    assert seg["image_prompts"] == ["a", "b"]
    assert not os.path.exists(video_path)  # invalidated since images changed


def test_images_style_does_not_invalidate_video_when_nothing_changed(tmp_path, monkeypatch):
    paths, m = _episode(tmp_path)
    video_path = os.path.join(paths["root"], m["segments"][0]["video"])
    _touch(video_path)
    _fake_generate_for_segment(monkeypatch, changed=False)

    pipeline.apply_images_to_segments(_ns("images"), paths, m, "Topic", "history", "images-pipeline-test")

    assert os.path.exists(video_path)  # left untouched -- cache reused, nothing changed


def test_images_style_skips_incomplete_segments(tmp_path, monkeypatch):
    paths, m = _episode(tmp_path)
    m["segments"][0]["status"] = "pending"
    calls = _fake_generate_for_segment(monkeypatch)

    pipeline.apply_images_to_segments(_ns("images"), paths, m, "Topic", "history", "images-pipeline-test")

    assert calls == []
