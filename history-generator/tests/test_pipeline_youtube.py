import os
from types import SimpleNamespace

import manifest as manifest_mod
import pipeline


def _episode(tmp_path):
    paths = manifest_mod.episode_paths(str(tmp_path), "yt-pipeline-test")
    manifest_mod.ensure_dirs(paths)
    script_path = os.path.join(paths["root"], "scripts/001.txt")
    os.makedirs(os.path.dirname(script_path), exist_ok=True)
    with open(script_path, "w") as f:
        f.write("Some narration script.")
    m = {
        "topic": "Test Topic",
        "title": "Test Title",
        "segment_gap_seconds": 1.5,
        "segments": [
            {
                "number": 1, "title": "Segment One", "script": "scripts/001.txt",
                "duration": 30.0, "status": "complete",
            },
        ],
    }
    return paths, m


def _ns(youtube_metadata=True, force=False):
    return SimpleNamespace(
        youtube_metadata=youtube_metadata, force=force,
        ollama_url="http://ollama", model="qwen3:32b",
    )


def test_disabled_is_a_noop(tmp_path, monkeypatch):
    paths, m = _episode(tmp_path)
    calls = []
    monkeypatch.setattr(pipeline.youtube_metadata, "generate", lambda *a, **k: calls.append(1))

    pipeline.apply_youtube_metadata(_ns(youtube_metadata=False), paths, m, "history")

    assert calls == []
    assert "youtube" not in m


def test_enabled_generates_and_stores_result(tmp_path, monkeypatch):
    paths, m = _episode(tmp_path)
    fake_result = {"title": "T", "description": "D", "tags": ["a"], "tags_joined": "a", "category": "Education", "chapters": "0:00 x", "generated_for_segment_count": 1}
    calls = []

    def fake_generate(ollama_url, model, domain, manifest_data, paths_arg, force=False):
        calls.append((ollama_url, model, domain, force))
        return fake_result

    monkeypatch.setattr(pipeline.youtube_metadata, "generate", fake_generate)

    pipeline.apply_youtube_metadata(_ns(), paths, m, "discovery")

    assert calls == [("http://ollama", "qwen3:32b", "discovery", False)]
    assert m["youtube"] == fake_result

    saved = manifest_mod.load_manifest(paths["manifest"])
    assert saved["youtube"] == fake_result


def test_failed_generation_leaves_manifest_untouched(tmp_path, monkeypatch):
    paths, m = _episode(tmp_path)
    monkeypatch.setattr(pipeline.youtube_metadata, "generate", lambda *a, **k: None)

    pipeline.apply_youtube_metadata(_ns(), paths, m, "discovery")

    assert "youtube" not in m


def test_force_is_threaded_through(tmp_path, monkeypatch):
    paths, m = _episode(tmp_path)
    seen = {}
    monkeypatch.setattr(
        pipeline.youtube_metadata, "generate",
        lambda ollama_url, model, domain, manifest_data, paths_arg, force=False: seen.setdefault("force", force),
    )

    pipeline.apply_youtube_metadata(_ns(force=True), paths, m, "discovery")

    assert seen["force"] is True
