import os
import subprocess
import wave

import pytest

import music
import music_catalog


def _make_track(path, freq=220.0, duration=2.0):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", f"sine=frequency={freq}:duration={duration}", "-c:a", "libmp3lame", path],
        check=True, capture_output=True,
    )


def _approved_entry(rel_file, track_id, energy="very-low", vocals=False, percussion=False, sleep_safe=True, category="sleep-ambient"):
    return {
        "id": track_id,
        "title": rel_file,
        "file": rel_file,
        "category": category,
        "tags": [category],
        "mood": category,
        "energy": energy,
        "vocals": vocals,
        "percussion": percussion,
        "sleep_safe": sleep_safe,
        "creator": None,
        "source_url": None,
        "license": None,
        "license_file": None,
        "duration_seconds": 2.0,
        "fingerprint": "irrelevant-for-these-tests",
    }


@pytest.fixture
def library(tmp_path):
    lib = str(tmp_path)
    _make_track(os.path.join(lib, "sleep-ambient", "approved.mp3"))
    _make_track(os.path.join(lib, "sleep-ambient", "unreviewed.mp3"))
    entries = [
        _approved_entry("sleep-ambient/approved.mp3", "approved-1"),
        {**_approved_entry("sleep-ambient/unreviewed.mp3", "unreviewed-1"), "sleep_safe": False, "energy": None, "vocals": None, "percussion": None},
    ]
    music_catalog.save(lib, entries)
    return lib


def test_resolve_track_by_explicit_id_bypasses_safety_filters(library):
    track, path = music.resolve_track(library, track_id="unreviewed-1")
    assert track["id"] == "unreviewed-1"
    assert os.path.isfile(path)


def test_resolve_track_unknown_id_raises(library):
    with pytest.raises(music.MusicError):
        music.resolve_track(library, track_id="nope")


def test_resolve_track_auto_select_only_considers_approved_tracks(library):
    track, path = music.resolve_track(library, mood="sleep-ambient", seed="episode-a")
    assert track["id"] == "approved-1"  # the only sleep_safe candidate
    assert os.path.isfile(path)


def test_resolve_track_auto_select_is_deterministic_per_seed(library):
    # Add a second approved candidate so seed actually matters.
    catalog = music_catalog.load(library)
    _make_track(os.path.join(library, "sleep-ambient", "approved2.mp3"))
    catalog.append(_approved_entry("sleep-ambient/approved2.mp3", "approved-2"))
    music_catalog.save(library, catalog)

    track_a1, _ = music.resolve_track(library, mood="sleep-ambient", seed="ancient-rome")
    track_a2, _ = music.resolve_track(library, mood="sleep-ambient", seed="ancient-rome")
    assert track_a1["id"] == track_a2["id"]  # same seed -> same pick, every time


def test_resolve_track_no_approved_candidates_raises_clear_error(library):
    with pytest.raises(music.MusicError, match="approved"):
        music.resolve_track(library, mood="no-such-mood", seed="x")


def test_resolve_track_missing_library_dir_raises(tmp_path):
    with pytest.raises(music.MusicError):
        music.resolve_track(str(tmp_path / "nope"), mood="sleep-ambient", seed="x")


def test_resolve_track_empty_catalog_raises(tmp_path):
    with pytest.raises(music.MusicError):
        music.resolve_track(str(tmp_path), mood="sleep-ambient", seed="x")


def test_resolve_track_rejects_path_traversal_in_catalog_entry(tmp_path):
    lib = str(tmp_path)
    entries = [_approved_entry("../../etc/passwd", "escape-1")]
    music_catalog.save(lib, entries)
    with pytest.raises(music.MusicError, match="escapes"):
        music.resolve_track(lib, track_id="escape-1")


def test_resolve_track_missing_file_on_disk_raises(tmp_path):
    lib = str(tmp_path)
    os.makedirs(os.path.join(lib, "sleep-ambient"))
    entries = [_approved_entry("sleep-ambient/ghost.mp3", "ghost-1")]
    music_catalog.save(lib, entries)
    with pytest.raises(music.MusicError, match="missing"):
        music.resolve_track(lib, track_id="ghost-1")


@pytest.mark.parametrize("value", [-40.0, -25.0, -6.0])
def test_validate_level_db_accepts_in_range(value):
    assert music.validate_level_db(value) == pytest.approx(value)


@pytest.mark.parametrize("value", [-41.0, -5.0, float("nan"), float("inf")])
def test_validate_level_db_rejects_invalid(value):
    with pytest.raises(music.MusicError):
        music.validate_level_db(value)


@pytest.mark.parametrize("value", [0.0, 8.0, 120.0])
def test_validate_fade_seconds_accepts_nonnegative(value):
    assert music.validate_fade_seconds(value) == pytest.approx(value)


@pytest.mark.parametrize("value", [-1.0, float("nan"), float("-inf")])
def test_validate_fade_seconds_rejects_invalid(value):
    with pytest.raises(music.MusicError):
        music.validate_fade_seconds(value)


def _wav_duration(path):
    with wave.open(path, "rb") as w:
        return w.getnframes() / w.getframerate()


def test_prepare_loops_short_track_to_exact_duration(tmp_path, library):
    track_path = os.path.join(library, "sleep-ambient", "approved.mp3")  # ~2s source
    out = str(tmp_path / "prepared.wav")
    music.prepare(track_path, duration_seconds=6.0, level_db=-25, fade_in_seconds=1, fade_out_seconds=1, out_path=out)
    assert _wav_duration(out) == pytest.approx(6.0, abs=0.15)


def test_prepare_trims_long_track_to_exact_duration(tmp_path, library):
    long_track = os.path.join(library, "sleep-ambient", "long.mp3")
    _make_track(long_track, duration=10.0)
    out = str(tmp_path / "prepared.wav")
    music.prepare(long_track, duration_seconds=3.0, level_db=-25, fade_in_seconds=0.5, fade_out_seconds=0.5, out_path=out)
    assert _wav_duration(out) == pytest.approx(3.0, abs=0.15)


def test_prepare_clamps_fades_that_exceed_duration(tmp_path, library):
    track_path = os.path.join(library, "sleep-ambient", "approved.mp3")
    out = str(tmp_path / "prepared.wav")
    # fade_in + fade_out (100 + 100) would exceed the 4s duration; must not error, must
    # still land on exactly the requested duration.
    music.prepare(track_path, duration_seconds=4.0, level_db=-25, fade_in_seconds=100, fade_out_seconds=100, out_path=out)
    assert _wav_duration(out) == pytest.approx(4.0, abs=0.15)


def test_prepare_leaves_source_file_unchanged(tmp_path, library):
    track_path = os.path.join(library, "sleep-ambient", "approved.mp3")
    before = music_catalog.sha256_file(track_path)
    music.prepare(track_path, duration_seconds=3.0, level_db=-25, fade_in_seconds=1, fade_out_seconds=1, out_path=str(tmp_path / "prepared.wav"))
    after = music_catalog.sha256_file(track_path)
    assert before == after
