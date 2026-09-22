import os

import manifest as manifest_mod
import pytest
import youtube_metadata


def test_format_timestamp_without_hours():
    assert youtube_metadata.format_timestamp(0, use_hours=False) == "0:00"
    assert youtube_metadata.format_timestamp(69, use_hours=False) == "1:09"
    assert youtube_metadata.format_timestamp(3599, use_hours=False) == "59:59"


def test_format_timestamp_with_hours():
    assert youtube_metadata.format_timestamp(0, use_hours=True) == "0:00:00"
    assert youtube_metadata.format_timestamp(3661, use_hours=True) == "1:01:01"
    assert youtube_metadata.format_timestamp(4444, use_hours=True) == "1:14:04"


def test_compute_chapters_empty_segments():
    chapters, total = youtube_metadata.compute_chapters([], gap_seconds=1.5)
    assert chapters == ""
    assert total == 0.0


def test_compute_chapters_matches_video_assembly_timeline():
    # Mirrors the exact arithmetic video.py's build_episode_video uses: N complete
    # segments contribute N-1 gaps, and each segment's start time is the sum of every
    # prior segment's duration plus a gap.
    segments = [
        {"title": "First", "duration": 60.0},
        {"title": "Second", "duration": 90.0},
        {"title": "Third", "duration": 30.0},
    ]
    chapters, total = youtube_metadata.compute_chapters(segments, gap_seconds=1.5)
    lines = chapters.split("\n")
    assert lines[0] == "0:00 First"
    assert lines[1] == "1:01 Second"  # 60 + 1.5 gap = 61.5 -> floors to 1:01
    assert lines[2] == "2:33 Third"  # 60 + 1.5 + 90 + 1.5 = 153 -> 2:33
    assert total == 60.0 + 1.5 + 90.0 + 1.5 + 30.0


def test_compute_chapters_uses_hours_format_past_one_hour():
    segments = [{"title": "A", "duration": 3700.0}, {"title": "B", "duration": 60.0}]
    chapters, total = youtube_metadata.compute_chapters(segments, gap_seconds=0.0)
    assert chapters.split("\n")[1].startswith("1:01:40")
    assert total == 3760.0


@pytest.fixture
def episode(tmp_path):
    paths = manifest_mod.episode_paths(str(tmp_path), "yt-test")
    manifest_mod.ensure_dirs(paths)
    for n, text in ((1, "First segment script."), (2, "Second segment script.")):
        script_path = os.path.join(paths["root"], f"scripts/{n:03d}.txt")
        os.makedirs(os.path.dirname(script_path), exist_ok=True)
        with open(script_path, "w") as f:
            f.write(text)
    manifest_data = {
        "title": "Test Episode",
        "topic": "Test Episode",
        "domain": "discovery",
        "segment_gap_seconds": 1.5,
        "segments": [
            {"number": 1, "title": "First", "script": "scripts/001.txt", "duration": 60.0, "status": "complete"},
            {"number": 2, "title": "Second", "script": "scripts/002.txt", "duration": 90.0, "status": "complete"},
        ],
    }
    return paths, manifest_data


def test_generate_returns_none_with_no_complete_segments(episode, monkeypatch):
    paths, m = episode
    m["segments"] = [{"number": 1, "title": "A", "status": "pending"}]
    monkeypatch.setattr(youtube_metadata.ollama_client, "chat_tool", lambda *a, **k: pytest.fail("should not be called"))

    result = youtube_metadata.generate("http://ollama", "qwen3:32b", "discovery", m, paths)
    assert result is None


def test_generate_calls_ollama_and_shapes_result(episode, monkeypatch):
    paths, m = episode
    seen = {}

    def fake_chat_tool(ollama_url, model, system, user, tool, temperature=0.5, timeout=300):
        seen["user"] = user
        return {
            "title": "A Great Title",
            "description": "A great description.",
            "tags": ["  space  ", "cosmos", "", "science"],
            "category": "Education",
        }

    monkeypatch.setattr(youtube_metadata.ollama_client, "chat_tool", fake_chat_tool)

    result = youtube_metadata.generate("http://ollama", "qwen3:32b", "discovery", m, paths)

    assert result["title"] == "A Great Title"
    assert result["tags"] == ["space", "cosmos", "science"]  # blank/whitespace-only entries dropped
    assert result["tags_joined"] == "space, cosmos, science"
    assert result["category"] == "Education"
    assert result["generated_for_segment_count"] == 2
    assert "0:00 First" in result["chapters"]
    assert "First segment script." in seen["user"]
    assert "Second segment script." in seen["user"]


def test_generate_is_cached_when_segment_count_unchanged(episode, monkeypatch):
    paths, m = episode
    calls = []
    monkeypatch.setattr(
        youtube_metadata.ollama_client, "chat_tool",
        lambda *a, **k: calls.append(1) or {"title": "T", "description": "D", "tags": ["a"], "category": "Education"},
    )

    first = youtube_metadata.generate("http://ollama", "qwen3:32b", "discovery", m, paths)
    m["youtube"] = first
    second = youtube_metadata.generate("http://ollama", "qwen3:32b", "discovery", m, paths)

    assert second == first
    assert len(calls) == 1  # not called again


def test_generate_regenerates_when_segment_count_grows(episode, monkeypatch):
    paths, m = episode
    calls = []
    monkeypatch.setattr(
        youtube_metadata.ollama_client, "chat_tool",
        lambda *a, **k: calls.append(1) or {"title": "T", "description": "D", "tags": ["a"], "category": "Education"},
    )

    m["youtube"] = youtube_metadata.generate("http://ollama", "qwen3:32b", "discovery", m, paths)
    m["segments"].append(
        {"number": 3, "title": "Third", "script": "scripts/002.txt", "duration": 30.0, "status": "complete"}
    )

    youtube_metadata.generate("http://ollama", "qwen3:32b", "discovery", m, paths)
    assert len(calls) == 2


def test_generate_force_regenerates_even_when_unchanged(episode, monkeypatch):
    paths, m = episode
    calls = []
    monkeypatch.setattr(
        youtube_metadata.ollama_client, "chat_tool",
        lambda *a, **k: calls.append(1) or {"title": "T", "description": "D", "tags": ["a"], "category": "Education"},
    )

    m["youtube"] = youtube_metadata.generate("http://ollama", "qwen3:32b", "discovery", m, paths)
    youtube_metadata.generate("http://ollama", "qwen3:32b", "discovery", m, paths, force=True)
    assert len(calls) == 2


def test_generate_returns_none_and_does_not_raise_on_ollama_failure(episode, monkeypatch):
    paths, m = episode

    def boom(*a, **k):
        raise RuntimeError("ollama unreachable")

    monkeypatch.setattr(youtube_metadata.ollama_client, "chat_tool", boom)

    result = youtube_metadata.generate("http://ollama", "qwen3:32b", "discovery", m, paths)
    assert result is None
