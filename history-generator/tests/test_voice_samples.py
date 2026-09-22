import os
import subprocess

import pytest

import voice_samples


def _make_tone_bytes(duration_seconds, freq=440.0):
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tf:
        tmp_path = tf.name
    try:
        subprocess.run(
            [
                "ffmpeg", "-y", "-f", "lavfi", "-i", f"sine=frequency={freq}:duration={duration_seconds}",
                "-c:a", "libmp3lame", tmp_path,
            ],
            check=True, capture_output=True,
        )
        with open(tmp_path, "rb") as f:
            return f.read()
    finally:
        os.remove(tmp_path)


def _ffprobe_duration(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


@pytest.mark.parametrize("bad_id", ["../etc/passwd", "af heart", "af/heart", "", "af;rm -rf"])
def test_sample_path_rejects_unsafe_voice_ids(tmp_path, bad_id):
    with pytest.raises(voice_samples.VoiceSampleError):
        voice_samples.sample_path(str(tmp_path), bad_id)


def test_sample_path_accepts_normal_voice_ids(tmp_path):
    p = voice_samples.sample_path(str(tmp_path), "af_heart")
    assert p == os.path.join(str(tmp_path), "af_heart.mp3")


def test_get_or_create_synthesizes_and_trims_to_max_duration(tmp_path, monkeypatch):
    calls = []

    def fake_synthesize(base_url, model, voice, text, speed=1.0, **kwargs):
        calls.append((voice, text, speed))
        return _make_tone_bytes(20.0)  # longer than the sample cap, to prove trimming happens

    monkeypatch.setattr(voice_samples.kokoro_client, "synthesize", fake_synthesize)

    path = voice_samples.get_or_create("http://kokoro", "af_heart", str(tmp_path))

    assert len(calls) == 1
    assert calls[0][0] == "af_heart"
    assert calls[0][2] == 1.0
    assert os.path.exists(path)
    assert _ffprobe_duration(path) <= voice_samples.SAMPLE_DURATION_SECONDS + 0.5
    # no leftover raw intermediate file
    assert not os.path.exists(path + ".raw")


def test_get_or_create_is_cached_on_second_call(tmp_path, monkeypatch):
    calls = []

    def fake_synthesize(base_url, model, voice, text, speed=1.0, **kwargs):
        calls.append(voice)
        return _make_tone_bytes(5.0)

    monkeypatch.setattr(voice_samples.kokoro_client, "synthesize", fake_synthesize)

    path1 = voice_samples.get_or_create("http://kokoro", "af_heart", str(tmp_path))
    path2 = voice_samples.get_or_create("http://kokoro", "af_heart", str(tmp_path))

    assert path1 == path2
    assert len(calls) == 1  # second call was a cache hit, no re-synthesis


def test_get_or_create_different_voices_are_cached_separately(tmp_path, monkeypatch):
    def fake_synthesize(base_url, model, voice, text, speed=1.0, **kwargs):
        return _make_tone_bytes(3.0)

    monkeypatch.setattr(voice_samples.kokoro_client, "synthesize", fake_synthesize)

    path_a = voice_samples.get_or_create("http://kokoro", "af_heart", str(tmp_path))
    path_b = voice_samples.get_or_create("http://kokoro", "am_adam", str(tmp_path))

    assert path_a != path_b
    assert os.path.exists(path_a)
    assert os.path.exists(path_b)
