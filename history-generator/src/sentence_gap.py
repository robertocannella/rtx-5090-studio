"""Configurable pauses between sentences within a single narration segment.

Kokoro synthesizes whatever text it's given as one continuous take, with whatever
pacing it chooses at sentence boundaries -- there's no parameter to ask it for a
specific pause length. To get a *consistent, configurable* pause, each sentence in the
segment script is synthesized separately, silence-trimmed at both ends (so any pause
Kokoro already produced is normalized away rather than stacked with the requested one --
this is what keeps the result from having a natural pause *plus* an inserted one), and
the trimmed clips are concatenated with exactly `sentence_gap_seconds` of silence between
them. `sentence_gap_seconds == 0` (or a single-sentence script) skips all of this and
makes the one Kokoro call the pipeline always used to make, so behavior and audio are
byte-for-byte unchanged from before this feature existed.
"""

import math
import os
import re
import subprocess

import kokoro_client

MIN_SENTENCE_GAP_SECONDS = 0.0
MAX_SENTENCE_GAP_SECONDS = 2.0
DEFAULT_SENTENCE_GAP_SECONDS = 0.5

# Trim silence more aggressively than this threshold/duration at each clip's start/end
# before re-joining with the configured gap.
_SILENCE_THRESHOLD_DB = -50
_SILENCE_TRIM_DURATION = 0.05

# A conservative list of common abbreviations (given without their own trailing period)
# that must never be treated as a sentence end. Not exhaustive -- this is narration
# prose, not a general-purpose NLP tokenizer.
ABBREVIATIONS = {
    "mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st", "vs", "etc", "mt", "gen",
    "rev", "capt", "col", "sgt", "lt", "no", "vol", "fig", "approx", "ca", "cf",
    "e.g", "i.e", "u.s", "u.k", "u.n", "a.d", "b.c",
}

_PUNCT_RE = re.compile(r'[.!?]+["\')\]]*')

# Multi-part dotted abbreviations (U.S., U.K., U.N., e.g., i.e., a.d., b.c., ...) show up
# to the main splitter as a run of *separate* one-letter-plus-period matches, so by the
# time the first period is seen there's no way yet to tell "U." apart from a real
# sentence end. Mask their internal dots first so the splitter never considers them.
_MULTI_DOT_ABBR_RE = re.compile(r"\b(?:[A-Za-z]\.){2,}")
_DOT_SENTINEL = "\x00"


class SentenceGapError(Exception):
    pass


def _run(cmd):
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise SentenceGapError(f"command failed: {' '.join(cmd)}\n{result.stderr[-2000:]}")


def validate_sentence_gap_seconds(value):
    """Coerce to float and enforce the finite, in-range contract. Raises SentenceGapError."""
    try:
        v = float(value)
    except (TypeError, ValueError) as e:
        raise SentenceGapError(f"sentence_gap_seconds must be a number, got {value!r}") from e
    if not math.isfinite(v):
        raise SentenceGapError(f"sentence_gap_seconds must be finite, got {v}")
    if not (MIN_SENTENCE_GAP_SECONDS <= v <= MAX_SENTENCE_GAP_SECONDS):
        raise SentenceGapError(
            f"sentence_gap_seconds must be between {MIN_SENTENCE_GAP_SECONDS} and "
            f"{MAX_SENTENCE_GAP_SECONDS}, got {v}"
        )
    return v


def split_sentences(text):
    """Split narration text into sentences, sentence-ending punctuation kept.

    Splits at a run of `.`/`!`/`?` only when: it isn't a decimal point between two
    digits (`3.14`), the word immediately before it isn't a known abbreviation (`Dr.`,
    `U.S.`, `e.g.`), and what follows (after whitespace) looks like the start of a new
    sentence (uppercase letter, digit, or opening quote) or is the end of the text.
    """
    text = text.strip()
    if not text:
        return []

    protected = _MULTI_DOT_ABBR_RE.sub(lambda m: m.group(0).replace(".", _DOT_SENTINEL), text)

    sentences = []
    start = 0
    for m in _PUNCT_RE.finditer(protected):
        end = m.end()
        bare = m.group().rstrip("\"')]")
        if bare == "." and end - 2 >= 0 and protected[end - 2].isdigit() and end < len(protected) and protected[end].isdigit():
            continue  # decimal point, e.g. "3.14"

        preceding = re.search(r"(\S+)$", protected[start:m.start() + 1])
        token = preceding.group(1).lower().rstrip(".") if preceding else ""
        if token in ABBREVIATIONS:
            continue

        rest = protected[end:].lstrip(" ")
        if rest and not (rest[0].isupper() or rest[0].isdigit() or rest[0] in "\"'“"):
            continue

        sentence = protected[start:end].strip()
        if sentence:
            sentences.append(sentence)
        start = end

    tail = protected[start:].strip()
    if tail:
        sentences.append(tail)
    return [s.replace(_DOT_SENTINEL, ".") for s in sentences]


def _trim_silence(in_path, out_path):
    """Strip leading/trailing silence from a clip -- see module docstring for why."""
    cmd = [
        "ffmpeg", "-y", "-i", in_path,
        "-af", (
            f"silenceremove=start_periods=1:start_duration={_SILENCE_TRIM_DURATION}:"
            f"start_threshold={_SILENCE_THRESHOLD_DB}dB:detection=peak,areverse,"
            f"silenceremove=start_periods=1:start_duration={_SILENCE_TRIM_DURATION}:"
            f"start_threshold={_SILENCE_THRESHOLD_DB}dB:detection=peak,areverse"
        ),
        "-c:a", "libmp3lame", "-b:a", "192k",
        out_path,
    ]
    _run(cmd)


def _make_silence(duration_seconds, out_path):
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "anullsrc=channel_layout=mono:sample_rate=24000",
        "-t", f"{duration_seconds:.3f}",
        "-c:a", "libmp3lame", "-b:a", "192k",
        out_path,
    ]
    _run(cmd)


def _concat_escape(path):
    return os.path.abspath(path).replace("'", "'\\''")


def synthesize_segment(kokoro_url, voice, speed, text, sentence_gap_seconds, out_path):
    """Synthesize `text` to out_path, one Kokoro call per sentence when
    sentence_gap_seconds > 0 and there's more than one sentence, joined with exactly
    sentence_gap_seconds of silence at each boundary. Otherwise makes a single Kokoro
    call over the whole text, same as always.
    """
    sentences = split_sentences(text) if sentence_gap_seconds > 0 else []

    if sentence_gap_seconds <= 0 or len(sentences) <= 1:
        audio_bytes = kokoro_client.synthesize(kokoro_url, "kokoro", voice, text, speed=speed)
        with open(out_path, "wb") as f:
            f.write(audio_bytes)
        return out_path

    tmp_dir = os.path.dirname(out_path)
    base = os.path.splitext(os.path.basename(out_path))[0]
    temp_files = []
    try:
        trimmed_paths = []
        for i, sentence in enumerate(sentences):
            raw_path = os.path.join(tmp_dir, f".{base}.sentence{i:03d}.raw.mp3")
            trimmed_path = os.path.join(tmp_dir, f".{base}.sentence{i:03d}.trimmed.mp3")
            temp_files += [raw_path, trimmed_path]

            audio_bytes = kokoro_client.synthesize(kokoro_url, "kokoro", voice, sentence, speed=speed)
            with open(raw_path, "wb") as f:
                f.write(audio_bytes)
            _trim_silence(raw_path, trimmed_path)
            trimmed_paths.append(trimmed_path)

        silence_path = os.path.join(tmp_dir, f".{base}.sentence_gap.mp3")
        temp_files.append(silence_path)
        _make_silence(sentence_gap_seconds, silence_path)

        concat_list = os.path.join(tmp_dir, f".{base}.sentence_concat.txt")
        temp_files.append(concat_list)
        with open(concat_list, "w") as f:
            for i, p in enumerate(trimmed_paths):
                f.write(f"file '{_concat_escape(p)}'\n")
                if i < len(trimmed_paths) - 1:
                    f.write(f"file '{_concat_escape(silence_path)}'\n")

        _run([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_list,
            "-c:a", "libmp3lame", "-b:a", "192k",
            out_path,
        ])
    finally:
        for p in temp_files:
            if os.path.exists(p):
                os.remove(p)

    return out_path
