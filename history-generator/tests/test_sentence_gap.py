import os
import subprocess
import tempfile

import pytest

import sentence_gap


@pytest.mark.parametrize("value", [-0.1, 2.1, float("nan"), float("inf"), float("-inf")])
def test_validate_sentence_gap_seconds_rejects_invalid(value):
    with pytest.raises(sentence_gap.SentenceGapError):
        sentence_gap.validate_sentence_gap_seconds(value)


@pytest.mark.parametrize("value", [0.0, 0.5, 1.0, 2.0])
def test_validate_sentence_gap_seconds_accepts_in_range(value):
    assert sentence_gap.validate_sentence_gap_seconds(value) == value


def test_split_sentences_empty_text():
    assert sentence_gap.split_sentences("") == []
    assert sentence_gap.split_sentences("   ") == []


def test_split_sentences_basic():
    text = "The reef was vast. Divers explored it for hours."
    assert sentence_gap.split_sentences(text) == [
        "The reef was vast.",
        "Divers explored it for hours.",
    ]


def test_split_sentences_question_and_exclamation():
    text = "Is that a giant squid? Yes! It truly is."
    assert sentence_gap.split_sentences(text) == [
        "Is that a giant squid?",
        "Yes!",
        "It truly is.",
    ]


def test_split_sentences_no_terminal_punctuation():
    assert sentence_gap.split_sentences("just a fragment") == ["just a fragment"]


@pytest.mark.parametrize("abbrev_text", [
    "Dr. Smith led the expedition. It succeeded.",
    "The site was named after St. Brendan. Sailors still visit.",
    "Compare this to the U.S. approach. It differs sharply.",
])
def test_split_sentences_does_not_split_on_abbreviations(abbrev_text):
    sentences = sentence_gap.split_sentences(abbrev_text)
    assert len(sentences) == 2
    assert sentences[1] in ("It succeeded.", "Sailors still visit.", "It differs sharply.")


def test_split_sentences_does_not_split_decimal_numbers():
    text = "The sample weighed 3.14 grams total. Researchers were surprised."
    sentences = sentence_gap.split_sentences(text)
    assert sentences == [
        "The sample weighed 3.14 grams total.",
        "Researchers were surprised.",
    ]


def _make_tone_bytes(duration_seconds, freq=440.0):
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


def test_synthesize_segment_zero_gap_makes_a_single_call(tmp_path, monkeypatch):
    calls = []

    def fake_synthesize(base_url, model, voice, text, speed=1.0, **kwargs):
        calls.append(text)
        return _make_tone_bytes(2.0)

    monkeypatch.setattr(sentence_gap.kokoro_client, "synthesize", fake_synthesize)

    out_path = os.path.join(str(tmp_path), "001.mp3")
    text = "First sentence here. Second sentence follows."
    sentence_gap.synthesize_segment("http://kokoro", "af_heart", 1.0, text, 0.0, out_path)

    assert len(calls) == 1
    assert calls[0] == text
    assert os.path.exists(out_path)


def test_synthesize_segment_single_sentence_makes_a_single_call_even_with_gap(tmp_path, monkeypatch):
    calls = []

    def fake_synthesize(base_url, model, voice, text, speed=1.0, **kwargs):
        calls.append(text)
        return _make_tone_bytes(1.5)

    monkeypatch.setattr(sentence_gap.kokoro_client, "synthesize", fake_synthesize)

    out_path = os.path.join(str(tmp_path), "001.mp3")
    sentence_gap.synthesize_segment("http://kokoro", "af_heart", 1.0, "Just one sentence here.", 0.5, out_path)

    assert len(calls) == 1


def test_synthesize_segment_multi_sentence_inserts_gaps_and_cleans_up(tmp_path, monkeypatch):
    calls = []

    def fake_synthesize(base_url, model, voice, text, speed=1.0, **kwargs):
        calls.append(text)
        return _make_tone_bytes(1.0)

    monkeypatch.setattr(sentence_gap.kokoro_client, "synthesize", fake_synthesize)

    out_path = os.path.join(str(tmp_path), "001.mp3")
    text = "First sentence here. Second sentence follows. Third one wraps up."
    sentence_gap.synthesize_segment("http://kokoro", "af_heart", 1.0, text, 0.5, out_path)

    assert len(calls) == 3  # one Kokoro call per sentence
    assert os.path.exists(out_path)

    duration = _ffprobe_duration(out_path)
    # 3 one-second tones (silence-trimmed, so close to 1.0s each) + 2 gaps of 0.5s.
    assert duration == pytest.approx(3 * 1.0 + 2 * 0.5, abs=0.3)

    leftovers = [f for f in os.listdir(str(tmp_path)) if f != "001.mp3"]
    assert leftovers == []
