import json
import os
import subprocess

import pytest

import music_catalog


def _make_track(path, freq=220.0, duration=1.0):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", f"sine=frequency={freq}:duration={duration}", "-c:a", "libmp3lame", path],
        check=True, capture_output=True,
    )


def test_scan_empty_library_returns_empty_catalog(tmp_path):
    summary = music_catalog.scan(str(tmp_path))
    assert summary == {"added": [], "updated": [], "missing": [], "duplicates": [], "total": 0}
    assert music_catalog.load(str(tmp_path)) == []


def test_scan_missing_library_raises(tmp_path):
    with pytest.raises(music_catalog.CatalogError):
        music_catalog.scan(str(tmp_path / "does-not-exist"))


def test_scan_discovers_new_tracks_unreviewed(tmp_path):
    _make_track(str(tmp_path / "sleep-ambient" / "a.mp3"))
    summary = music_catalog.scan(str(tmp_path))
    assert summary["added"] == ["sleep-ambient/a.mp3"]
    assert summary["total"] == 1

    catalog = music_catalog.load(str(tmp_path))
    entry = catalog[0]
    assert entry["file"] == "sleep-ambient/a.mp3"
    assert entry["category"] == "sleep-ambient"
    assert entry["sleep_safe"] is False
    assert entry["duration_seconds"] == pytest.approx(1.0, abs=0.05)
    assert entry["fingerprint"]


def test_scan_preserves_human_edited_metadata_on_rescan(tmp_path):
    _make_track(str(tmp_path / "sleep-ambient" / "a.mp3"))
    music_catalog.scan(str(tmp_path))

    catalog = music_catalog.load(str(tmp_path))
    catalog[0]["sleep_safe"] = True
    catalog[0]["vocals"] = False
    catalog[0]["percussion"] = False
    catalog[0]["energy"] = "very-low"
    catalog[0]["tags"] = ["sleep-ambient", "hand-reviewed"]
    music_catalog.save(str(tmp_path), catalog)

    summary = music_catalog.scan(str(tmp_path))
    assert summary["added"] == []
    assert summary["updated"] == []

    catalog = music_catalog.load(str(tmp_path))
    entry = catalog[0]
    assert entry["sleep_safe"] is True
    assert entry["energy"] == "very-low"
    assert entry["tags"] == ["sleep-ambient", "hand-reviewed"]


def test_scan_resets_sleep_safe_when_file_content_changes(tmp_path):
    track_path = str(tmp_path / "sleep-ambient" / "a.mp3")
    _make_track(track_path, freq=220.0)
    music_catalog.scan(str(tmp_path))

    catalog = music_catalog.load(str(tmp_path))
    catalog[0]["sleep_safe"] = True
    music_catalog.save(str(tmp_path), catalog)

    # Replace the file's content at the same path -- fingerprint changes.
    _make_track(track_path, freq=440.0)
    summary = music_catalog.scan(str(tmp_path))
    assert summary["updated"] == ["sleep-ambient/a.mp3"]

    catalog = music_catalog.load(str(tmp_path))
    assert catalog[0]["sleep_safe"] is False


def test_scan_keeps_entries_for_missing_files(tmp_path):
    track_path = str(tmp_path / "sleep-ambient" / "a.mp3")
    _make_track(track_path)
    music_catalog.scan(str(tmp_path))

    os.remove(track_path)
    summary = music_catalog.scan(str(tmp_path))
    assert summary["missing"] == ["sleep-ambient/a.mp3"]
    assert summary["total"] == 1  # entry retained, not deleted


def test_scan_deduplicates_byte_identical_files(tmp_path):
    # Filenames chosen so "a.mp3" sorts first (scan() processes files in sorted order
    # and keeps whichever path it sees first as canonical).
    _make_track(str(tmp_path / "sleep-ambient" / "a.mp3"), freq=220.0)
    import shutil
    shutil.copyfile(str(tmp_path / "sleep-ambient" / "a.mp3"), str(tmp_path / "sleep-ambient" / "z-copy.mp3"))

    summary = music_catalog.scan(str(tmp_path))
    assert summary["total"] == 1
    assert len(summary["duplicates"]) == 1
    assert summary["duplicates"][0]["file"] == "sleep-ambient/z-copy.mp3"
    assert summary["duplicates"][0]["duplicate_of"] == "sleep-ambient/a.mp3"


def test_scan_ignores_unsupported_extensions(tmp_path):
    os.makedirs(str(tmp_path / "sleep-ambient"))
    with open(str(tmp_path / "sleep-ambient" / "notes.txt"), "w") as f:
        f.write("not audio")
    summary = music_catalog.scan(str(tmp_path))
    assert summary["total"] == 0


def test_new_entry_never_claims_a_license_without_a_matching_certificate(tmp_path):
    _make_track(str(tmp_path / "sleep-ambient" / "untitled-123456.mp3"))
    music_catalog.scan(str(tmp_path))
    entry = music_catalog.load(str(tmp_path))[0]
    assert entry["license"] is None
    assert entry["license_file"] is None
    assert entry["creator"] is None
    assert entry["source_url"] is None


def test_new_entry_picks_up_matching_pixabay_license_certificate(tmp_path):
    track_dir = tmp_path / "sleep-ambient"
    _make_track(str(track_dir / "artist-track-123456.mp3"))
    (track_dir / "artist-track-123456-license.txt").write_text(
        "Licensor's Username:\nhttps://pixabay.com/users/someone-1/\n\n"
        "Audio File URL:\nhttps://pixabay.com/music/track-123456/\n"
    )

    music_catalog.scan(str(tmp_path))
    entry = music_catalog.load(str(tmp_path))[0]
    assert entry["license_file"] == "sleep-ambient/artist-track-123456-license.txt"
    assert entry["creator"] == "https://pixabay.com/users/someone-1/"
    assert entry["source_url"] == "https://pixabay.com/music/track-123456/"
    # The certificate is recorded; we still never assert a license verdict ourselves.
    assert entry["license"] is None
