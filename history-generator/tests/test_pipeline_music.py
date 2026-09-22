import os
import subprocess
from types import SimpleNamespace

import manifest as manifest_mod
import music
import music_catalog
import pipeline
import pytest


def _make_track(path, freq=220.0, duration=2.0):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", f"sine=frequency={freq}:duration={duration}", "-c:a", "libmp3lame", path],
        check=True, capture_output=True,
    )


def _approved_entry(rel_file, track_id, fingerprint):
    return {
        "id": track_id,
        "title": rel_file,
        "file": rel_file,
        "category": "sleep-ambient",
        "tags": ["sleep-ambient"],
        "mood": "sleep-ambient",
        "energy": "very-low",
        "vocals": False,
        "percussion": False,
        "sleep_safe": True,
        "creator": None,
        "source_url": None,
        "license": None,
        "license_file": None,
        "duration_seconds": 2.0,
        "fingerprint": fingerprint,
    }


@pytest.fixture
def library(tmp_path):
    lib = str(tmp_path / "library")
    track_path = os.path.join(lib, "sleep-ambient", "track.mp3")
    _make_track(track_path)
    fp = music_catalog.sha256_file(track_path)
    music_catalog.save(lib, [_approved_entry("sleep-ambient/track.mp3", "track-1", fp)])
    return lib


@pytest.fixture
def episode(tmp_path):
    paths = manifest_mod.episode_paths(str(tmp_path / "output"), "test-episode")
    manifest_mod.ensure_dirs(paths)
    audio_path = os.path.join(paths["root"], "audio", "001.mp3")
    _make_track(audio_path, freq=440.0, duration=3.0)
    script_path = os.path.join(paths["root"], "scripts", "001.txt")
    with open(script_path, "w") as f:
        f.write("Narration text.")
    m = {"segments": [{"number": 1, "audio": "audio/001.mp3", "script": "scripts/001.txt"}]}
    return paths, m


def _args(library, music=True, mood="sleep-ambient", track_id=None, level_db=-25.0, fade_in=1.0, fade_out=1.0, force=False):
    return SimpleNamespace(
        topic="Test Episode", music=music, music_mood=mood, music_track_id=track_id,
        music_level_db=level_db, music_fade_in_seconds=fade_in, music_fade_out_seconds=fade_out,
        music_library_dir=library, force=force,
    )


def test_disabled_is_noop_and_clears_stale_prepared_file(episode, library):
    paths, m = episode
    music_path = os.path.join(paths["video"], ".music.wav")
    with open(music_path, "wb") as f:
        f.write(b"stale-bytes")
    m["music"] = {"enabled": True, "track_id": "old-track"}

    result = pipeline.apply_music(_args(library, music=False), paths, m, 3.0, "test-episode")

    assert result is None
    assert m["music"]["enabled"] is False
    assert not os.path.exists(music_path)


def test_enabled_prepares_and_records_manifest_fields(episode, library):
    paths, m = episode
    result = pipeline.apply_music(_args(library), paths, m, 3.0, "test-episode")

    assert result == os.path.join(paths["video"], ".music.wav")
    assert os.path.getsize(result) > 0
    info = m["music"]
    assert info["enabled"] is True
    assert info["requested_mood"] == "sleep-ambient"
    assert info["track_id"] == "track-1"
    assert info["file"] == "sleep-ambient/track.mp3"
    assert info["level_db"] == -25.0
    assert info["fade_in_seconds"] == 1.0
    assert info["fade_out_seconds"] == 1.0
    assert info["duration_seconds"] == 3.0
    assert info["fingerprint"]
    assert info["prepared_path"] == os.path.relpath(result, paths["root"])


def test_unchanged_settings_do_not_reprepare(episode, library, monkeypatch):
    paths, m = episode
    pipeline.apply_music(_args(library), paths, m, 3.0, "test-episode")
    music_path = os.path.join(paths["video"], ".music.wav")
    mtime_before = os.path.getmtime(music_path)

    calls = []
    monkeypatch.setattr(pipeline.music, "prepare", lambda *a, **kw: calls.append(a))

    pipeline.apply_music(_args(library), paths, m, 3.0, "test-episode")
    assert calls == []
    assert os.path.getmtime(music_path) == mtime_before


@pytest.mark.parametrize("changed_kwargs", [
    {"level_db": -20.0},
    {"fade_in": 3.0},
    {"fade_out": 5.0},
])
def test_changed_level_or_fade_triggers_reprepare(episode, library, monkeypatch, changed_kwargs):
    paths, m = episode
    pipeline.apply_music(_args(library), paths, m, 3.0, "test-episode")

    real_prepare = pipeline.music.prepare
    calls = []
    monkeypatch.setattr(pipeline.music, "prepare", lambda *a, **kw: (calls.append(a), real_prepare(*a, **kw))[1])

    pipeline.apply_music(_args(library, **changed_kwargs), paths, m, 3.0, "test-episode")
    assert len(calls) == 1


def test_changed_duration_triggers_reprepare(episode, library, monkeypatch):
    paths, m = episode
    pipeline.apply_music(_args(library), paths, m, 3.0, "test-episode")

    real_prepare = pipeline.music.prepare
    calls = []
    monkeypatch.setattr(pipeline.music, "prepare", lambda *a, **kw: (calls.append(a), real_prepare(*a, **kw))[1])

    pipeline.apply_music(_args(library), paths, m, 5.0, "test-episode")  # episode grew
    assert len(calls) == 1


def test_file_content_change_at_same_path_is_detected_without_rescan(episode, library, monkeypatch):
    """Simulates someone replacing the library file's bytes without re-running the
    scanner: catalog.json still lists the old fingerprint, but apply_music hashes the
    file live each run, so a stale cache is never reused."""
    paths, m = episode
    pipeline.apply_music(_args(library), paths, m, 3.0, "test-episode")

    track_path = os.path.join(library, "sleep-ambient", "track.mp3")
    _make_track(track_path, freq=880.0, duration=2.0)  # different content, same path/catalog entry

    real_prepare = pipeline.music.prepare
    calls = []
    monkeypatch.setattr(pipeline.music, "prepare", lambda *a, **kw: (calls.append(a), real_prepare(*a, **kw))[1])

    pipeline.apply_music(_args(library), paths, m, 3.0, "test-episode")
    assert len(calls) == 1


def test_reenabling_after_disable_does_not_reuse_stale_soundtrack(episode, library):
    paths, m = episode
    music_path = os.path.join(paths["video"], ".music.wav")

    pipeline.apply_music(_args(library), paths, m, 3.0, "test-episode")
    first_bytes = open(music_path, "rb").read()

    pipeline.apply_music(_args(library, music=False), paths, m, 3.0, "test-episode")
    assert not os.path.exists(music_path)

    pipeline.apply_music(_args(library), paths, m, 3.0, "test-episode")
    assert os.path.exists(music_path)
    # Not asserting byte-for-byte difference (same source+settings could legitimately
    # reproduce identical output) -- the meaningful guarantee is the file was actually
    # regenerated (existed -> gone -> exists again), not silently left deleted/stale.
    assert os.path.getsize(music_path) > 0
    del first_bytes  # documents intent; no equality assertion needed


def test_enabled_with_no_approved_tracks_raises(episode, tmp_path):
    empty_lib = str(tmp_path / "empty-library")
    os.makedirs(empty_lib)
    music_catalog.save(empty_lib, [])
    paths, m = episode
    with pytest.raises(music.MusicError):
        pipeline.apply_music(_args(empty_lib), paths, m, 3.0, "test-episode")


def test_apply_music_never_touches_narration_or_script_files(episode, library):
    paths, m = episode
    audio_path = os.path.join(paths["root"], "audio", "001.mp3")
    script_path = os.path.join(paths["root"], "scripts", "001.txt")
    audio_before = music_catalog.sha256_file(audio_path)
    script_mtime_before = os.path.getmtime(script_path)

    pipeline.apply_music(_args(library), paths, m, 3.0, "test-episode")

    assert music_catalog.sha256_file(audio_path) == audio_before
    assert os.path.getmtime(script_path) == script_mtime_before
