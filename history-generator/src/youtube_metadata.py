"""YouTube upload metadata (title, description, tags, category, chapters) for a
finished episode, derived from its actual narration scripts.

Chapters are pure arithmetic over each segment's own duration and the episode's
segment_gap_seconds -- no LLM involved, and always exactly reproducible from the
manifest, matching the real timeline video.py assembles (see
video.py:build_episode_video's segment/gap sequencing). Title/description/tags/category
come from a single Ollama tool call over the full concatenated script -- one call per
episode, not per segment, since there's no per-item budget to divide the way image
prompts are split across a segment's images.

Both are cached in the manifest (under "youtube"), keyed on how many segments were
complete when generated: a resume that doesn't add segments never re-asks the model, and
one that does (e.g. after an outline extension) is treated as the content having grown
enough to regenerate. Best-effort throughout -- a failed Ollama call is logged and
skipped, never aborts the episode; the video still gets built without it.
"""

import os

import ollama_client
import prompts


class YoutubeMetadataError(Exception):
    pass


def format_timestamp(total_seconds, use_hours):
    total_seconds = int(total_seconds)
    h, rem = divmod(total_seconds, 3600)
    m, s = divmod(rem, 60)
    if use_hours:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def compute_chapters(segments, gap_seconds):
    """segments: complete segments, in number order, each with "duration" and "title".

    Returns (chapters_text, total_duration_seconds). chapters_text is a ready-to-paste
    "<timestamp> <title>" block, one line per segment -- computed purely from durations
    and the constant inter-segment gap, the same arithmetic video.py's own assembly
    follows, so these timestamps land exactly on each segment's real start time in the
    finished file.
    """
    if not segments:
        return "", 0.0
    cursor = 0.0
    entries = []
    for seg in segments:
        entries.append((cursor, seg["title"]))
        cursor += (seg.get("duration") or 0.0) + gap_seconds
    total_duration = cursor - gap_seconds
    use_hours = total_duration >= 3600
    lines = [f"{format_timestamp(t, use_hours)} {title}" for t, title in entries]
    return "\n".join(lines), total_duration


def generate(ollama_url, model, domain, manifest_data, paths, force=False):
    """Generate (or reuse the cached) YouTube metadata for this episode.

    Returns the metadata dict, or None if there's nothing to generate from yet (no
    complete segments) or the Ollama call failed -- both non-fatal to the caller.
    """
    complete = sorted(
        (s for s in manifest_data["segments"] if s.get("status") == "complete"),
        key=lambda s: s["number"],
    )
    if not complete:
        return None

    existing = manifest_data.get("youtube")
    if not force and existing and existing.get("generated_for_segment_count") == len(complete):
        return existing

    gap_seconds = manifest_data.get("segment_gap_seconds", 0.0)
    chapters, total_duration = compute_chapters(complete, gap_seconds)

    script_parts = []
    for seg in complete:
        with open(os.path.join(paths["root"], seg["script"])) as f:
            text = f.read().strip()
        script_parts.append(f"[Segment {seg['number']}: {seg['title']}]\n{text}")
    full_script = "\n\n".join(script_parts)

    title = manifest_data.get("title") or manifest_data["topic"]
    system = prompts.build_youtube_metadata_system(domain)
    user = prompts.build_youtube_metadata_user(manifest_data["topic"], title, domain, total_duration, full_script)
    tool = prompts.build_youtube_metadata_tool()

    try:
        args = ollama_client.chat_tool(ollama_url, model, system, user, tool, temperature=0.5, timeout=300)
    except Exception as e:  # noqa: BLE001 - best-effort; a failed call must not abort the episode
        print(f"     [warn] YouTube metadata generation failed, skipping: {e}")
        return None

    tags = [str(t).strip() for t in (args.get("tags") or []) if str(t).strip()]
    return {
        "title": str(args.get("title") or title)[:100],
        "description": str(args.get("description") or ""),
        "tags": tags,
        "tags_joined": ", ".join(tags),
        "category": args.get("category") or "Education",
        "chapters": chapters,
        "generated_for_segment_count": len(complete),
    }
