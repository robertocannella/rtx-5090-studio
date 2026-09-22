import json
import math
import os
import shutil
import subprocess

import ambient
import image_client
import manifest as manifest_mod
import math_visual
import music
import ollama_client
import pitch
import prompts
import segment_images
import sentence_gap
import textutil
import video
import youtube_metadata

SECONDS_PER_SEGMENT_ESTIMATE = 75
MAX_OUTLINE_EXTENSIONS = 8
MIN_SEGMENT_TARGET_SECONDS = 20.0


def slug_and_paths(topic, output_dir):
    slug = manifest_mod.slugify(topic)
    paths = manifest_mod.episode_paths(output_dir, slug)
    return slug, paths


def init_or_load_manifest(
    paths, topic, duration, voice, speed, pitch_semitones, sentence_gap_seconds, domain, model, force,
):
    if force and os.path.exists(paths["root"]):
        print(f"--force: removing existing episode directory {paths['root']}")
        shutil.rmtree(paths["root"])
    manifest_mod.ensure_dirs(paths)
    existing = None if force else manifest_mod.load_manifest(paths["manifest"])
    if existing:
        print(f"Resuming existing episode manifest: {paths['manifest']}")
        return existing
    return {
        "title": None,
        "topic": topic,
        "target_duration_seconds": duration,
        "voice": voice,
        "speed": speed,
        "pitch_semitones": pitch_semitones,
        "sentence_gap_seconds": sentence_gap_seconds,
        "domain": domain,
        "model": model,
        "segments": [],
    }


def resolve_domain(args, m):
    """The content domain (history/math/discovery/...) is chosen once per episode, like
    the topic itself -- every segment's script has to read consistently, so switching
    domains mid-episode isn't something a resume auto-applies (unlike voice/speed/pitch,
    which only affect how already-written text is spoken). A manifest from before this
    feature existed has no "domain" key at all; it's treated as "history" (which is what
    every prior episode's prompts actually asked for, so this is a no-op for old episodes).
    Use --force to start an episode over under a different domain.
    """
    stored = m.get("domain")
    if stored and stored != args.domain:
        print(
            f"[info] episode was created with domain={stored!r}; keeping it for this run "
            f"(--domain={args.domain!r} ignored -- use --force to start over under a new domain)"
        )
    domain = stored or args.domain
    m["domain"] = domain
    return domain


def apply_narration_params_to_segments(args, paths, m):
    """Reset generated narration/video produced with a different voice, speed, or
    sentence-gap setting.

    Voice and speed are baked directly into Kokoro's synthesized audio; sentence gaps
    change *how* that audio is produced (one Kokoro call per sentence, joined with
    silence, instead of one call over the whole script -- see sentence_gap.py). All
    three therefore require re-synthesizing narration from scratch, unlike pitch (a
    separate post-process layered on top of it, see apply_pitch_to_segments). Resets
    affected segments back to "pending" (clearing duration/status/error) and removes
    their raw narration, pitch-shifted narration, and per-segment video files so the
    normal segment-processing loop regenerates them. Segments not yet generated need no
    changes. Script text is untouched -- narration content doesn't depend on any of
    these three settings, so scripts are never regenerated.
    """
    prev_voice = m.get("voice")
    prev_speed = m.get("speed")
    prev_sentence_gap = m.get("sentence_gap_seconds", 0.0)
    if prev_voice == args.voice and prev_speed == args.speed and prev_sentence_gap == args.sentence_gap_seconds:
        return

    reset = []
    for seg in m["segments"]:
        touched = False
        for key in ("audio", "audio_pitched", "video"):
            rel = seg.get(key)
            if not rel:
                continue
            full = os.path.join(paths["root"], rel)
            if os.path.exists(full):
                os.remove(full)
                touched = True
        seg["audio_pitched"] = None
        seg.pop("pitch_semitones", None)
        if touched or seg["status"] != "pending":
            seg["duration"] = None
            seg["status"] = "pending"
            seg.pop("error", None)
            reset.append(seg["number"])

    if reset:
        print(
            f"narration settings changed (voice {prev_voice!r}->{args.voice!r}, "
            f"speed {prev_speed!r}->{args.speed!r}, sentence_gap {prev_sentence_gap!r}->{args.sentence_gap_seconds!r}); "
            f"re-synthesizing narration for {len(reset)} segment(s): {reset}"
        )
    m["voice"] = args.voice
    m["speed"] = args.speed
    m["sentence_gap_seconds"] = args.sentence_gap_seconds


def apply_visual_to_segments(args, paths, m, slug):
    """Keep every segment's video in sync with the currently-requested visual style.

    Picking a math visualization is a one-time, seed-deterministic choice per episode
    (math_visual.select_visual(slug)) made the first time visual_style becomes "math" for
    this episode, then reused on every subsequent run -- including if visual_style is
    toggled back to "static" and later back to "math" again -- so resuming or rebuilding
    an episode always reproduces the same background. The only way to get a *different*
    random selection is --force (which rebuilds the whole episode from scratch anyway, so
    there's no separate "reroll the visual" flag, matching how --force already reshuffles
    the ambient mood). Changing visual_style invalidates every complete segment's
    per-segment video (and any cached gap/background-mix clips) without touching
    narration, scripts, or audio -- the video is the only thing that depends on it.
    """
    prev_style = m.get("visual_style", math_visual.DEFAULT_VISUAL_STYLE)

    if args.visual_style == "math" and not m.get("visual"):
        m["visual"] = math_visual.select_visual(slug)
        print(f"     Selected math visualization: {m['visual']['family']}")

    if prev_style == args.visual_style:
        return

    touched = []
    for seg in m["segments"]:
        video_rel = seg.get("video")
        if not video_rel:
            continue
        video_path = os.path.join(paths["root"], video_rel)
        if os.path.exists(video_path):
            os.remove(video_path)
            touched.append(seg["number"])

    for stale_name in (".gap.mp4", ".math_bg.mp4", ".narrated.mp4"):
        stale_path = os.path.join(paths["video"], stale_name)
        if os.path.exists(stale_path):
            os.remove(stale_path)

    if touched:
        print(
            f"visual_style changed ({prev_style!r} -> {args.visual_style!r}); "
            f"rebuilding video for {len(touched)} segment(s): {touched}"
        )
    m["visual_style"] = args.visual_style


def apply_pitch_to_segments(args, paths, m):
    """Keep each complete segment's video in sync with the currently-requested pitch.

    The raw Kokoro narration (seg["audio"]) is never touched. When the requested pitch
    differs from what a segment's video was last built with, a pitch-shifted copy is
    (re)rendered into seg["audio_pitched"] and the stale per-segment video is deleted so
    build_episode_video regenerates it from the new narration -- without re-synthesizing
    speech. Runs over every complete segment on every call, so it also catches segments
    that were already complete before a resumed run changed pitch_semitones.
    """
    complete = [s for s in m["segments"] if s["status"] == "complete"]
    for seg in complete:
        n = seg["number"]
        prev_pitch = seg.get("pitch_semitones") or 0.0
        pitched_rel = seg.get("audio_pitched")
        pitched_exists = bool(pitched_rel) and os.path.exists(os.path.join(paths["root"], pitched_rel))

        if prev_pitch == args.pitch_semitones and (args.pitch_semitones == 0 or pitched_exists):
            continue

        video_path = os.path.join(paths["root"], seg["video"])
        if args.pitch_semitones == 0:
            seg["audio_pitched"] = None
        else:
            raw_path = os.path.join(paths["root"], seg["audio"])
            pitched_rel = f"audio/{n:03d}.pitch.mp3"
            pitched_path = os.path.join(paths["root"], pitched_rel)
            print(f"[{n:02d}] Applying pitch shift ({args.pitch_semitones:+.1f} semitones)...")
            pitch.shift(raw_path, pitched_path, args.pitch_semitones)
            seg["audio_pitched"] = pitched_rel

        seg["pitch_semitones"] = args.pitch_semitones
        if os.path.exists(video_path):
            os.remove(video_path)


def apply_images_to_segments(args, paths, m, topic, domain, slug):
    """Keep each complete segment's per-segment images in sync with visual_style="images".

    Runs after narration is fully synthesized (unlike math visual selection, which
    happens up front) because the number of images a segment gets depends on its actual
    narration duration -- see segment_images.images_for_duration. Cached like every other
    creative choice in this pipeline: a segment already holding the right number of
    images (and the prompts that produced them) is left untouched on resume, regenerated
    only when missing, incomplete, or --force'd. Whenever a segment's images actually
    change, its now-stale per-segment video is deleted so build_episode_video rebuilds it.

    Also frees ComfyUI's VRAM (image_client.free_memory) after any segment that actually
    triggered generation -- ComfyUI otherwise keeps FLUX's ~16GB of weights resident
    indefinitely, which starves Ollama of VRAM for as long as this loop runs (see
    image_client.free_memory's docstring for the concrete failure this caused). Doing it
    per-segment rather than once at the end of the whole episode bounds how long another
    job's Ollama calls can be starved to "at most one segment's worth of images," not the
    entire episode's image-generation phase.
    """
    if args.visual_style != "images":
        return

    complete = [s for s in m["segments"] if s["status"] == "complete"]
    for seg in complete:
        n = seg["number"]
        script_path = os.path.join(paths["root"], seg["script"])
        with open(script_path) as f:
            script_text = f.read()

        print(f"[{n:02d}] Preparing segment images...")
        rel_paths, seg_prompts, changed = segment_images.generate_for_segment(
            args.ollama_url, args.model, args.comfyui_url, domain, seg, script_text, slug, paths,
            force=args.force,
        )
        seg["images"] = rel_paths
        seg["image_prompts"] = seg_prompts

        if changed:
            video_path = os.path.join(paths["root"], seg["video"])
            if os.path.exists(video_path):
                os.remove(video_path)
            image_client.free_memory(args.comfyui_url)
        manifest_mod.save_manifest(paths["manifest"], m)


def apply_youtube_metadata(args, paths, m, domain):
    """Generate (or reuse the cached) YouTube upload metadata once narration is done --
    see youtube_metadata.py. Enabled by default (--no-youtube-metadata to disable, like
    --no-ambient). Best-effort: a failure here is logged and skipped by
    youtube_metadata.generate() itself, never aborts the episode -- the video still gets
    built either way.
    """
    if not getattr(args, "youtube_metadata", True):
        return
    print("Generating YouTube metadata...")
    result = youtube_metadata.generate(args.ollama_url, args.model, domain, m, paths, force=args.force)
    if result:
        m["youtube"] = result
        manifest_mod.save_manifest(paths["manifest"], m)


def apply_music(args, paths, m, duration_seconds, slug):
    """Resolve, prepare, and cache the episode's background music bed.

    Returns the prepared audio path, or None if music is disabled. Raises
    music.MusicError if music is explicitly enabled but can't be produced -- per the
    spec, an explicit request for music that can't be satisfied is a hard failure, not a
    silent video without a soundtrack (unlike ambient, which is best-effort by design).

    Only ever touches the library (read-only) and this episode's own prepared-music
    file; never the script, raw/pitched narration, or per-segment videos.
    """
    music_path = os.path.join(paths["video"], ".music.wav")

    if not getattr(args, "music", False):
        if (m.get("music") or {}).get("enabled"):
            m["music"] = {"enabled": False}
        if os.path.exists(music_path):
            os.remove(music_path)
        return None

    track, resolved_path = music.resolve_track(
        args.music_library_dir, track_id=args.music_track_id, mood=args.music_mood, seed=slug,
    )
    fp = music.fingerprint(resolved_path)

    prev = m.get("music") or {}
    needs_prepare = (
        args.force
        or not os.path.exists(music_path)
        or prev.get("track_id") != track["id"]
        or prev.get("fingerprint") != fp
        or prev.get("level_db") != args.music_level_db
        or prev.get("fade_in_seconds") != args.music_fade_in_seconds
        or prev.get("fade_out_seconds") != args.music_fade_out_seconds
        or prev.get("duration_seconds") != duration_seconds
    )
    if needs_prepare:
        print(f"     Preparing background music: {track.get('title') or track['id']}...")
        music.prepare(
            resolved_path, duration_seconds, args.music_level_db,
            args.music_fade_in_seconds, args.music_fade_out_seconds, music_path,
        )

    m["music"] = {
        "enabled": True,
        "requested_mood": args.music_mood,
        "track_id": track["id"],
        "file": track["file"],
        "fingerprint": fp,
        "level_db": args.music_level_db,
        "fade_in_seconds": args.music_fade_in_seconds,
        "fade_out_seconds": args.music_fade_out_seconds,
        "duration_seconds": duration_seconds,
        "prepared_path": os.path.relpath(music_path, paths["root"]),
    }
    return music_path


def total_duration(m):
    return sum(s.get("duration") or 0 for s in m["segments"] if s.get("status") == "complete")


def estimate_segment_target_seconds(remaining_seconds, segment_count, segment_gap_seconds):
    """Per-segment spoken-audio target, given a remaining time budget shared across
    segment_count segments with an inter-segment gap between each. Reserving the gap
    time up front (rather than budgeting narration alone) is what lets the requested
    --duration mean the finished video's length, not just the narration's.
    """
    if segment_count <= 0:
        return max(MIN_SEGMENT_TARGET_SECONDS, remaining_seconds)
    usable = remaining_seconds - segment_gap_seconds * max(0, segment_count - 1)
    return max(MIN_SEGMENT_TARGET_SECONDS, usable / segment_count)


def new_segment_entries(start_num, segs, target_seconds=SECONDS_PER_SEGMENT_ESTIMATE):
    entries = []
    for j, s in enumerate(segs):
        n = start_num + j
        entries.append({
            "number": n,
            "title": s.get("title", f"Segment {n}"),
            "summary": s.get("summary", ""),
            "script": f"scripts/{n:03d}.txt",
            "audio": f"audio/{n:03d}.mp3",
            "video": f"video/{n:03d}.mp4",
            "duration": None,
            "status": "pending",
            "target_seconds": target_seconds,
        })
    return entries


def ffprobe_duration(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", path],
        capture_output=True, text=True, check=True,
    )
    data = json.loads(out.stdout)
    return float(data["format"]["duration"])


def process_segment(args, paths, topic, domain, seg):
    n = seg["number"]
    print(f"[{n:02d}] {seg['title']}")
    script_path = os.path.join(paths["root"], seg["script"])
    audio_path = os.path.join(paths["root"], seg["audio"])

    try:
        if os.path.exists(script_path) and os.path.getsize(script_path) > 0:
            with open(script_path) as f:
                text = f.read()
        else:
            print("     Generating script...")
            prompt = prompts.build_segment_prompt(
                topic, seg,
                target_seconds=seg.get("target_seconds") or SECONDS_PER_SEGMENT_ESTIMATE,
                speed=args.speed, sentence_gap_seconds=args.sentence_gap_seconds, domain=domain,
            )
            segment_system = prompts.DOMAINS[domain]["segment_system"]
            text = ollama_client.chat_text(args.ollama_url, args.model, segment_system, prompt)
            text = textutil.sanitize_narration(text)
            if not text:
                raise RuntimeError("empty script generated")
            with open(script_path, "w") as f:
                f.write(text)

        if not (os.path.exists(audio_path) and os.path.getsize(audio_path) > 0):
            print("     Generating narration...")
            sentence_gap.synthesize_segment(
                args.kokoro_url, args.voice, args.speed, text, args.sentence_gap_seconds, audio_path,
            )

        duration = ffprobe_duration(audio_path)
        seg["duration"] = round(duration, 1)
        seg["status"] = "complete"
        seg.pop("error", None)
        print(f"     Duration: {duration:.1f} sec")
    except Exception as e:  # noqa: BLE001 - a failed segment must not abort the run
        seg["status"] = "failed"
        seg["error"] = str(e)
        print(f"     [error] segment {n} failed: {e}")


def run(args):
    try:
        args.pitch_semitones = pitch.validate(getattr(args, "pitch_semitones", 0.0))
    except pitch.PitchError as e:
        print(f"[error] {e}")
        return None
    if args.pitch_semitones != 0 and not pitch.available():
        print(
            f"[error] pitch_semitones={args.pitch_semitones} requested but ffmpeg lacks the "
            "'rubberband' filter (built without --enable-librubberband); rerun with "
            "pitch_semitones=0 or use an ffmpeg build that includes it."
        )
        return None

    if getattr(args, "music", False):
        try:
            args.music_level_db = music.validate_level_db(getattr(args, "music_level_db", -25.0))
            args.music_fade_in_seconds = music.validate_fade_seconds(
                getattr(args, "music_fade_in_seconds", 8.0), "music_fade_in_seconds",
            )
            args.music_fade_out_seconds = music.validate_fade_seconds(
                getattr(args, "music_fade_out_seconds", 20.0), "music_fade_out_seconds",
            )
        except music.MusicError as e:
            print(f"[error] {e}")
            return None

    try:
        args.segment_gap_seconds = video.validate_gap_seconds(
            getattr(args, "segment_gap_seconds", video.DEFAULT_GAP_SECONDS)
        )
    except video.VideoError as e:
        print(f"[error] {e}")
        return None

    try:
        args.sentence_gap_seconds = sentence_gap.validate_sentence_gap_seconds(
            getattr(args, "sentence_gap_seconds", sentence_gap.DEFAULT_SENTENCE_GAP_SECONDS)
        )
    except sentence_gap.SentenceGapError as e:
        print(f"[error] {e}")
        return None

    try:
        args.visual_style = math_visual.validate_visual_style(
            getattr(args, "visual_style", math_visual.DEFAULT_VISUAL_STYLE)
        )
    except math_visual.MathVisualError as e:
        print(f"[error] {e}")
        return None

    try:
        args.domain = prompts.validate_domain(getattr(args, "domain", prompts.DEFAULT_DOMAIN))
    except prompts.DomainError as e:
        print(f"[error] {e}")
        return None

    slug, paths = slug_and_paths(args.topic, args.output_dir)
    m = init_or_load_manifest(
        paths, args.topic, args.duration, args.voice, args.speed,
        args.pitch_semitones, args.sentence_gap_seconds, args.domain, args.model, args.force,
    )
    domain = resolve_domain(args, m)
    apply_narration_params_to_segments(args, paths, m)
    apply_visual_to_segments(args, paths, m, slug)
    m["segment_gap_seconds"] = args.segment_gap_seconds
    manifest_mod.save_manifest(paths["manifest"], m)

    print(f"Episode: {args.topic}")
    print(f"Domain: {domain}")
    print(f"Target: {args.duration} seconds")
    print()

    if not m["segments"]:
        est_count = max(3, math.ceil(args.duration / SECONDS_PER_SEGMENT_ESTIMATE) + 2)
        seg_target = estimate_segment_target_seconds(args.duration, est_count, args.segment_gap_seconds)
        print(f"Generating episode outline ({est_count} segments, ~{seg_target:.0f}s each)...")
        outline = ollama_client.chat_json(
            args.ollama_url, args.model, prompts.DOMAINS[domain]["outline_system"],
            prompts.build_outline_prompt(args.topic, est_count, [], domain=domain),
        )
        m["title"] = outline.get("title") or args.topic
        m["segments"] = new_segment_entries(1, outline.get("segments", []), seg_target)
        manifest_mod.save_manifest(paths["manifest"], m)
    elif not m.get("title"):
        m["title"] = args.topic

    extensions_used = 0
    idx = 0
    running_total = total_duration(m)

    while running_total < args.duration:
        while idx < len(m["segments"]):
            seg = m["segments"][idx]
            idx += 1
            if seg["status"] == "complete":
                continue
            process_segment(args, paths, args.topic, domain, seg)
            manifest_mod.save_manifest(paths["manifest"], m)
            running_total = total_duration(m)
            print(f"     Total: {running_total:.1f} / {args.duration}")
            print()
            if running_total >= args.duration:
                break

        if running_total >= args.duration:
            break

        if extensions_used >= MAX_OUTLINE_EXTENSIONS:
            print("[warn] Reached maximum outline extensions; stopping short of target duration.")
            break

        remaining = args.duration - running_total
        extra_count = max(2, math.ceil(remaining / SECONDS_PER_SEGMENT_ESTIMATE))
        seg_target = estimate_segment_target_seconds(remaining, extra_count, args.segment_gap_seconds)
        existing_titles = [s["title"] for s in m["segments"]]
        print(f"Narration at {running_total:.1f}s, below target {args.duration}s — generating {extra_count} more segment(s), ~{seg_target:.0f}s each...")
        outline = ollama_client.chat_json(
            args.ollama_url, args.model, prompts.DOMAINS[domain]["outline_system"],
            prompts.build_outline_prompt(args.topic, extra_count, existing_titles, domain=domain),
        )
        new_entries = new_segment_entries(len(m["segments"]) + 1, outline.get("segments", []), seg_target)
        m["segments"].extend(new_entries)
        manifest_mod.save_manifest(paths["manifest"], m)
        extensions_used += 1

    complete = [s for s in m["segments"] if s["status"] == "complete"]
    failed = [s for s in m["segments"] if s["status"] == "failed"]
    print(
        f"Narration complete: {len(complete)} segment(s), {running_total:.1f}s total"
        + (f", {len(failed)} failed" if failed else "")
    )

    if not complete:
        print("[error] No completed segments; cannot build video.")
        return None

    try:
        apply_pitch_to_segments(args, paths, m)
    except pitch.PitchError as e:
        print(f"[error] pitch shifting failed: {e}")
        return None
    manifest_mod.save_manifest(paths["manifest"], m)

    try:
        apply_images_to_segments(args, paths, m, args.topic, domain, slug)
    except segment_images.SegmentImagesError as e:
        print(f"[error] segment image generation failed: {e}")
        return None

    apply_youtube_metadata(args, paths, m, domain)

    # Gaps are inserted between segments (never within one), so N complete segments
    # contribute N-1 gaps. Background beds are prepared/rendered to this full length --
    # not just the narration total -- so music/ambient keep playing through the pauses
    # instead of running out and going silent before the video ends.
    gap_count = max(0, len(complete) - 1)
    gap_total = args.segment_gap_seconds * gap_count
    video_duration = running_total + gap_total
    print(
        f"Segments: {len(complete)} complete; inter-segment gaps inserted: {gap_count} "
        f"({args.segment_gap_seconds:.1f}s each, {gap_total:.1f}s total)"
    )
    print(f"Estimated final video duration: {video_duration:.1f}s (target {args.duration}s)")

    ambient_audio_path = None
    if getattr(args, "ambient", True):
        if not m.get("ambient") or args.force:
            print()
            print("Designing ambient audio bed...")
            m["ambient"] = ambient.design(args.ollama_url, args.model, args.topic, m["title"])
            manifest_mod.save_manifest(paths["manifest"], m)

        ambient_audio_path = os.path.join(paths["video"], ".ambient.wav")
        if not os.path.exists(ambient_audio_path) or args.force:
            print("     Rendering ambient bed...")
            try:
                ambient.render(m["ambient"], video_duration, ambient_audio_path)
            except ambient.AmbientError as e:
                print(f"     [warn] ambient rendering failed, continuing without ambient audio: {e}")
                ambient_audio_path = None

    try:
        music_audio_path = apply_music(args, paths, m, video_duration, slug)
    except music.MusicError as e:
        print(f"[error] background music failed: {e}")
        return None
    manifest_mod.save_manifest(paths["manifest"], m)

    final_path = os.path.join(paths["final"], f"{slug}.mp4")
    print()
    print("Building video...")
    try:
        video.build_episode_video(
            paths, m, final_path,
            ambient_audio_path=ambient_audio_path, music_audio_path=music_audio_path,
            gap_seconds=args.segment_gap_seconds,
            visual=m.get("visual") if args.visual_style == "math" else None,
            visual_style=args.visual_style,
            force=args.force,
        )
    except video.VideoError as e:
        print(f"[error] Video assembly failed: {e}")
        return None

    actual_duration = ffprobe_duration(final_path)
    print(f"Final video: {final_path}")
    print(f"Actual duration: {actual_duration:.1f}s (estimated {video_duration:.1f}s, target {args.duration}s)")

    return {
        "slug": slug,
        "paths": paths,
        "manifest": m,
        "final_path": final_path,
        "narration_seconds": running_total,
        "segment_gap_count": gap_count,
        "video_duration_estimated": video_duration,
        "video_duration_actual": actual_duration,
        "failed": failed,
    }
