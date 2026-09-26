import math
import os
import subprocess

from PIL import ImageFont

import math_visual

FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
BG_COLOR = "0x141414"
TITLE_COLOR = "white"
SEGMENT_COLOR = "0xE8B94A"
RESOLUTION = "1920x1080"
FRAME_WIDTH = 1920
FPS = "30"

EPISODE_TITLE_MAX_FONTSIZE = 60
SEGMENT_TITLE_MAX_FONTSIZE = 80
MIN_TITLE_FONTSIZE = 32
# Leaves a margin on both sides of the frame rather than letting text run edge to edge.
TITLE_MAX_WIDTH_RATIO = 0.92

_font_cache = {}


def _measure_text_width(text, fontsize):
    font = _font_cache.get(fontsize)
    if font is None:
        font = ImageFont.truetype(FONT_PATH, fontsize)
        _font_cache[fontsize] = font
    return font.getlength(text)


def _fit_fontsize(text, max_fontsize, frame_width=FRAME_WIDTH, min_fontsize=MIN_TITLE_FONTSIZE):
    """The largest fontsize <= max_fontsize at which `text` (rendered in FONT_PATH) fits
    within TITLE_MAX_WIDTH_RATIO of frame_width. ffmpeg's drawtext filter has no built-in
    shrink-to-fit -- a single fixed fontsize that looks right for a short title clips
    badly off both edges of the frame for a long one (confirmed against a real
    76-character episode title, which overflowed both sides at a fixed fontsize=60).
    Measured with Pillow against the actual font file rather than an approximate
    average-character-width guess -- a rough per-character heuristic gave inconsistent
    results across even two real titles while this was being worked out, since real
    character widths vary a lot (a capitalized, W/M-heavy title is much wider than an
    equally-long one full of narrow lowercase letters).
    """
    fontsize = max_fontsize
    max_width = frame_width * TITLE_MAX_WIDTH_RATIO
    while fontsize > min_fontsize and _measure_text_width(text, fontsize) > max_width:
        fontsize -= 2
    return fontsize

MIN_GAP_SECONDS = 0.0
MAX_GAP_SECONDS = 10.0
DEFAULT_GAP_SECONDS = 1.5

# How long the crossfade transition between two consecutive segment images lasts.
# Clamped down per-segment (see _images_input_and_filter) when a segment has so many
# images relative to its duration that a fixed 1.5s would eat more than half a slice.
IMAGE_FADE_SECONDS = 1.5


class VideoError(Exception):
    pass


def validate_gap_seconds(value):
    """Coerce to float and enforce the finite, in-range contract. Raises VideoError."""
    try:
        v = float(value)
    except (TypeError, ValueError) as e:
        raise VideoError(f"segment_gap_seconds must be a number, got {value!r}") from e
    if not math.isfinite(v):
        raise VideoError(f"segment_gap_seconds must be finite, got {v}")
    if not (MIN_GAP_SECONDS <= v <= MAX_GAP_SECONDS):
        raise VideoError(
            f"segment_gap_seconds must be between {MIN_GAP_SECONDS} and {MAX_GAP_SECONDS}, got {v}"
        )
    return v


def _run(cmd):
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise VideoError(f"command failed: {' '.join(cmd)}\n{result.stderr[-2000:]}")


def _write_textfile(path, text):
    with open(path, "w") as f:
        f.write(text)


def _probe_duration(path):
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
        capture_output=True, text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise VideoError(f"could not probe duration of {path}: {result.stderr[-500:]}")
    return float(result.stdout.strip())


def _images_input_and_filter(image_paths, narration_duration, resolution, fps):
    """Build the ffmpeg inputs + filter_complex fragment that turns a segment's still
    images into one crossfaded video clip exactly narration_duration long, ending at
    output label "vimg" (or "s0" for the single-image case, where no crossfade is
    needed). Each image is scaled/cropped to fill `resolution` before crossfading, since
    FLUX doesn't guarantee an exact-pixel match to the video's own resolution.

    The offset math for chaining N-1 xfade filters follows ffmpeg's own documented
    multi-input recipe: with each input clip d seconds long and a fade seconds long,
    the k-th xfade (1-indexed, joining image k into the chain) starts at
    offset = k * (d - fade); the combined output ends up N*d - (N-1)*fade seconds long.
    Solving that for d given a target total (narration_duration) is what lets this
    produce an exact-duration clip regardless of image count.
    """
    n = len(image_paths)
    crop = resolution.replace("x", ":")

    if n == 1:
        return (
            ["-loop", "1", "-t", f"{narration_duration:.3f}", "-i", image_paths[0]],
            f"[0:v]scale={resolution}:force_original_aspect_ratio=increase,crop={crop},"
            f"setsar=1,format=yuv420p,fps={fps}[s0]",
            "s0",
        )

    fade = min(IMAGE_FADE_SECONDS, (narration_duration / n) * 0.5)
    slice_dur = (narration_duration + (n - 1) * fade) / n

    inputs = []
    for p in image_paths:
        inputs += ["-loop", "1", "-t", f"{slice_dur:.3f}", "-i", p]

    scale_filters = ";".join(
        f"[{i}:v]scale={resolution}:force_original_aspect_ratio=increase,crop={crop},"
        f"setsar=1,format=yuv420p,fps={fps}[s{i}]"
        for i in range(n)
    )

    chain = []
    prev_label = "s0"
    for i in range(1, n):
        out_label = f"x{i}" if i < n - 1 else "vimg"
        offset = i * (slice_dur - fade)
        chain.append(f"[{prev_label}][s{i}]xfade=transition=fade:duration={fade:.3f}:offset={offset:.3f}[{out_label}]")
        prev_label = out_label

    filter_complex = scale_filters + ";" + ";".join(chain)
    return inputs, filter_complex, prev_label


def build_segment_video(paths, episode_title, seg, math_bg_path=None, image_paths=None, force=False):
    n = seg["number"]
    narration_rel = seg.get("audio_pitched") or seg["audio"]
    audio_path = os.path.join(paths["root"], narration_rel)
    video_path = os.path.join(paths["root"], seg["video"])
    if os.path.exists(video_path) and os.path.getsize(video_path) > 0 and not force:
        return video_path

    narration_duration = _probe_duration(audio_path)

    tmp_dir = paths["video"]
    ep_title_file = os.path.join(tmp_dir, ".episode_title.txt")
    seg_title_file = os.path.join(tmp_dir, f".segment_title_{n:03d}.txt")
    _write_textfile(ep_title_file, episode_title)
    _write_textfile(seg_title_file, seg["title"])

    # The math/image backgrounds are busier than the plain dark backdrop, so a
    # translucent band is drawn behind each line of text first to keep it legible --
    # fixed-height bands (not sized to the actual text) since drawbox can't see a later
    # drawtext's measured width/height in the same filter chain.
    busy_background = bool(math_bg_path) or bool(image_paths)
    legibility_backdrop = (
        "drawbox=x=0:y=70:w=iw:h=100:color=black@0.45:t=fill,"
        "drawbox=x=0:y=(ih/2-80):w=iw:h=160:color=black@0.45:t=fill,"
        if busy_background else ""
    )
    ep_fontsize = _fit_fontsize(episode_title, EPISODE_TITLE_MAX_FONTSIZE)
    seg_fontsize = _fit_fontsize(seg["title"], SEGMENT_TITLE_MAX_FONTSIZE)
    text_filter = (
        f"drawtext=fontfile={FONT_PATH}:textfile={ep_title_file}:fontsize={ep_fontsize}:fontcolor={TITLE_COLOR}:"
        f"x=(w-text_w)/2:y=100,"
        f"drawtext=fontfile={FONT_PATH}:textfile={seg_title_file}:fontsize={seg_fontsize}:fontcolor={SEGMENT_COLOR}:"
        f"x=(w-text_w)/2:y=(h-text_h)/2"
    )

    if image_paths:
        bg_input, bg_filter, bg_label = _images_input_and_filter(image_paths, narration_duration, RESOLUTION, FPS)
        filter_complex = f"{bg_filter};[{bg_label}]{legibility_backdrop}{text_filter}[v]"
        audio_input_index = len(image_paths)
    elif math_bg_path:
        # -stream_loop -1 repeats the (seamlessly-looping) rendered clip to cover
        # whatever this segment's actual narration duration turns out to be.
        bg_input = ["-stream_loop", "-1", "-i", math_bg_path]
        filter_complex = f"[0:v]scale={RESOLUTION}:flags=bilinear,{legibility_backdrop}{text_filter}[v]"
        audio_input_index = 1
    else:
        bg_input = ["-f", "lavfi", "-i", f"color=c={BG_COLOR}:s={RESOLUTION}:r={FPS}"]
        filter_complex = f"[0:v]{text_filter}[v]"
        audio_input_index = 1

    cmd = [
        "ffmpeg", "-y",
        *bg_input,
        "-i", audio_path,
        "-filter_complex", filter_complex,
        "-map", "[v]", "-map", f"{audio_input_index}:a",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        # -shortest alone is unreliable here: with an infinite lavfi color source behind
        # a filter_complex, it doesn't always stop the video stream exactly at the
        # narration's end (observed ~1.8-2s of silent overrun in practice). An explicit
        # -t pinned to the probed narration duration is what actually guarantees the
        # video and audio streams end together.
        "-t", f"{narration_duration:.3f}",
        "-shortest",
        video_path,
    ]
    _run(cmd)
    return video_path


def _build_gap_clip(paths, gap_seconds, math_bg_path=None):
    """A silent, blank clip inserted between segments in the concat list, so background
    music/ambient (and, when enabled, the math visualization) keeps playing through the
    pause instead of the audio/video just stopping.

    Rebuilt on every call rather than cached across runs -- it's a trivial sub-second
    ffmpeg encode, so there's no stale-duration bug to guard against by skipping it.
    """
    gap_path = os.path.join(paths["video"], ".gap.mp4")
    if math_bg_path:
        bg_input = ["-stream_loop", "-1", "-i", math_bg_path]
        video_filter = ["-vf", f"scale={RESOLUTION}:flags=bilinear"]
    else:
        bg_input = ["-f", "lavfi", "-i", f"color=c={BG_COLOR}:s={RESOLUTION}:r={FPS}:d={gap_seconds:.3f}"]
        video_filter = []
    cmd = [
        "ffmpeg", "-y",
        *bg_input,
        "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
        *video_filter,
        "-t", f"{gap_seconds:.3f}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        gap_path,
    ]
    _run(cmd)
    return gap_path


def _get_or_render_math_bg(paths, visual, force=False):
    """Render (or reuse the cached) math-visualization loop clip for this episode.

    Cached at video/.math_bg.mp4, keyed purely on existence -- like the ambient bed, it's
    a one-time creative choice per episode (see math_visual.select_visual / pipeline.py's
    apply_visual_to_segments) that's meant to survive resumes untouched; it's rebuilt only
    when missing or explicitly --force'd, never because narration/music/other settings
    changed. Returns None (no math background) when visual is falsy.
    """
    if not visual:
        return None
    bg_path = os.path.join(paths["video"], ".math_bg.mp4")
    if os.path.exists(bg_path) and os.path.getsize(bg_path) > 0 and not force:
        return bg_path
    math_visual.render_loop(visual, math_visual.RENDER_RESOLUTION, FPS, math_visual.DEFAULT_LOOP_SECONDS, bg_path)
    return bg_path


def _concat_clips(clip_paths, target_path):
    """Join clip_paths (segment videos, interleaved with any gap clips, in order) into
    target_path.

    Uses ffmpeg's concat *filter* (decoded-frame concatenation inside one ffmpeg process),
    not the concat *demuxer* (`-f concat`, container-level packet stitching). The demuxer
    was found to badly miscalculate output duration once more than one short clip (e.g. a
    segment gap under ~2s) appears in the sequence -- reproduced consistently on this
    project's ffmpeg build (7.1.5): a true ~78s sequence (3 segments + 2 gaps) came out at
    113s, while the same sequence with 0 or 1 gap was fine. The filter approach doesn't
    have this failure mode, so it's used unconditionally, not just when gaps are present.
    Segment clips and the gap clip aren't guaranteed to share the same audio sample
    rate/channel layout (segments inherit Kokoro's, currently 24kHz mono; the gap clip is
    generated at 48kHz stereo -- see _build_gap_clip), so each input's audio is explicitly
    normalized before concatenation rather than relying on implicit format negotiation.
    """
    if len(clip_paths) == 1:
        cmd = [
            "ffmpeg", "-y", "-i", clip_paths[0],
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
            "-movflags", "+faststart",
            target_path,
        ]
        _run(cmd)
        return target_path

    inputs = []
    for p in clip_paths:
        inputs += ["-i", p]
    n = len(clip_paths)
    branches = "".join(
        f"[{i}:v]setpts=PTS-STARTPTS[v{i}];"
        f"[{i}:a]aformat=sample_rates=48000:channel_layouts=stereo,asetpts=PTS-STARTPTS[a{i}];"
        for i in range(n)
    )
    concat_inputs = "".join(f"[v{i}][a{i}]" for i in range(n))
    filter_complex = f"{branches}{concat_inputs}concat=n={n}:v=1:a=1[v][a]"

    cmd = [
        "ffmpeg", "-y",
        *inputs,
        "-filter_complex", filter_complex,
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        target_path,
    ]
    _run(cmd)
    return target_path


def build_episode_video(
    paths, manifest_data, final_path, ambient_audio_path=None, music_audio_path=None,
    gap_seconds=0.0, visual=None, visual_style=None, force=False,
):
    complete = [s for s in manifest_data["segments"] if s["status"] == "complete"]
    complete.sort(key=lambda s: s["number"])
    if not complete:
        raise VideoError("no completed segments to assemble")

    # The rendered loop clip restarts (from its own phase 0) at every segment and gap
    # boundary rather than continuing a single whole-episode phase -- each segment/gap is
    # rendered independently (and independently cached, for resumability), and segment
    # boundaries are already hard content cuts (new title, new narration), so a background
    # loop restart there reads as intentional rather than as an unexplained mid-scene jump.
    # True cross-segment phase continuity was considered and rejected: it would require
    # every segment's render to depend on the exact durations of all segments before it,
    # breaking per-segment caching for what's a subtle, easy-to-miss visual difference.
    math_bg_path = _get_or_render_math_bg(paths, visual, force=force)

    episode_title = manifest_data.get("title") or manifest_data["topic"]
    clip_paths = []
    for seg in complete:
        image_paths = None
        if visual_style == "images" and seg.get("images"):
            image_paths = [os.path.join(paths["root"], p) for p in seg["images"]]
        clip_paths.append(
            build_segment_video(paths, episode_title, seg, math_bg_path=math_bg_path, image_paths=image_paths, force=force)
        )

    gap_path = (
        _build_gap_clip(paths, gap_seconds, math_bg_path=math_bg_path)
        if gap_seconds > 0 and len(clip_paths) > 1 else None
    )

    sequence = []
    for i, p in enumerate(clip_paths):
        sequence.append(p)
        if gap_path is not None and i < len(clip_paths) - 1:
            sequence.append(gap_path)

    background_paths = [p for p in (ambient_audio_path, music_audio_path) if p]
    target_path = os.path.join(paths["video"], ".narrated.mp4") if background_paths else final_path
    _concat_clips(sequence, target_path)

    if background_paths:
        _mix_background(target_path, background_paths, final_path)

    return final_path


def _mix_background(narrated_path, background_paths, final_path):
    """Mix narration with one or more background beds (ambient and/or music).

    normalize=0 keeps each branch's own pre-set level (ambient's bed_level_db, music's
    music_level_db) rather than averaging them down; alimiter is the safety net against
    clipping when narration plus multiple background layers sum too hot.
    """
    n = len(background_paths)
    inputs = ["-i", narrated_path]
    for p in background_paths:
        inputs += ["-i", p]
    labels = "".join(f"[{i}:a]" for i in range(n + 1))
    filter_complex = (
        f"{labels}amix=inputs={n + 1}:normalize=0:duration=first:dropout_transition=2,"
        f"alimiter=limit=0.97[aout]"
    )
    cmd = [
        "ffmpeg", "-y",
        *inputs,
        "-filter_complex", filter_complex,
        "-map", "0:v", "-map", "[aout]",
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        final_path,
    ]
    _run(cmd)
