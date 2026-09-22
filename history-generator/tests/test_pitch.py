import math
import os
import struct
import subprocess
import wave

import pytest

import pitch


def _make_tone(path, freq=220.0, duration=2.0, sample_rate=48000):
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", f"sine=frequency={freq}:duration={duration}:sample_rate={sample_rate}",
            "-c:a", "pcm_s16le",
            path,
        ],
        check=True, capture_output=True,
    )


def _decode_to_wav(src_path, wav_path):
    subprocess.run(
        ["ffmpeg", "-y", "-i", src_path, "-ac", "1", "-c:a", "pcm_s16le", wav_path],
        check=True, capture_output=True,
    )


def _wav_duration(path):
    with wave.open(path, "rb") as w:
        return w.getnframes() / w.getframerate()


def _estimate_frequency(wav_path):
    """Rough zero-crossing-rate frequency estimate; fine for a near-pure sine tone."""
    with wave.open(wav_path, "rb") as w:
        assert w.getsampwidth() == 2
        n = w.getnframes()
        rate = w.getframerate()
        channels = w.getnchannels()
        raw = w.readframes(n)
    samples = struct.unpack(f"<{n * channels}h", raw)
    if channels > 1:
        samples = samples[0::channels]
    crossings = sum(1 for i in range(1, len(samples)) if samples[i - 1] <= 0 < samples[i])
    duration = len(samples) / rate
    return crossings / duration


@pytest.fixture
def tone_wav(tmp_path):
    path = str(tmp_path / "tone.wav")
    _make_tone(path)
    return path


def test_pitch_factor_matches_formula():
    assert pitch.pitch_factor(0) == 1.0
    assert math.isclose(pitch.pitch_factor(12), 2.0, rel_tol=1e-9)
    assert math.isclose(pitch.pitch_factor(-12), 0.5, rel_tol=1e-9)


def test_available_detects_rubberband():
    assert pitch.available() is True


@pytest.mark.parametrize("value", [0.0, -4.0, 4.0, -2.5, 3.9])
def test_validate_accepts_in_range(value):
    assert pitch.validate(value) == pytest.approx(value)


@pytest.mark.parametrize("value", [-4.1, 4.1, -100, 100])
def test_validate_rejects_out_of_range(value):
    with pytest.raises(pitch.PitchError):
        pitch.validate(value)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_validate_rejects_non_finite(value):
    with pytest.raises(pitch.PitchError):
        pitch.validate(value)


def test_validate_rejects_non_numeric():
    with pytest.raises(pitch.PitchError):
        pitch.validate("not a number")


def test_shift_preserves_duration(tmp_path, tone_wav):
    out = str(tmp_path / "shifted.mp3")
    pitch.shift(tone_wav, out, 2.0)
    assert os.path.getsize(out) > 0

    original_duration = _wav_duration(tone_wav)
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", out],
        capture_output=True, text=True, check=True,
    )
    shifted_duration = float(result.stdout.strip())
    assert shifted_duration == pytest.approx(original_duration, abs=0.15)


@pytest.mark.parametrize("semitones,expected_ratio", [(12.0, 2.0), (-12.0, 0.5)])
def test_shift_changes_pitch_in_expected_direction(tmp_path, tone_wav, semitones, expected_ratio):
    out_mp3 = str(tmp_path / f"shifted_{semitones}.mp3")
    pitch.shift(tone_wav, out_mp3, semitones)

    decoded_wav = str(tmp_path / f"shifted_{semitones}_decoded.wav")
    _decode_to_wav(out_mp3, decoded_wav)

    original_freq = _estimate_frequency(tone_wav)
    shifted_freq = _estimate_frequency(decoded_wav)

    assert shifted_freq == pytest.approx(original_freq * expected_ratio, rel=0.15)


def test_zero_semitones_is_the_identity_transform():
    # The "skip processing entirely at 0" behavior lives in
    # pipeline.apply_pitch_to_segments (see test_pipeline_pitch.py); this just confirms
    # the underlying factor math treats 0 semitones as a no-op.
    assert pitch.pitch_factor(0.0) == 1.0
