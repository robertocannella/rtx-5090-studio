"""Per-segment AI-generated image backgrounds (visual_style="images").

Generates a short sequence of stills per segment -- how many depends on the segment's
narration length, see images_for_duration -- which video.py cross-fades between to cover
the segment's whole runtime. Two GPU-backed calls happen here per segment: an Ollama tool
call proposes concrete, on-topic visual scene descriptions from the segment's own script
(rather than generic stock-art), then ComfyUI renders each one via FLUX.1-schnell (see
image_client.py). Both go through gpu_lock so they never run at the same time as anything
else touching the GPU (see gpu_lock.py).

Caching follows the same philosophy as the rest of the pipeline (music.py, math_visual.py
via video.py): a segment's images and the prompts that produced them are kept once
generated -- resuming or rebuilding an episode reuses them untouched -- and are only
regenerated when missing, incomplete, or --force'd. The image *prompts* come from an LLM
rather than a seeded random choice, so unlike math_visual's selection they aren't
reproducible from the episode slug alone; caching by presence is what keeps a resumed
episode's images stable instead of re-rolling on every run.
"""

import hashlib
import os

import image_client
import ollama_client
import prompts

SECONDS_PER_IMAGE = 15.0
MIN_IMAGES_PER_SEGMENT = 2
MAX_IMAGES_PER_SEGMENT = 6

# 16:9, matching video.py's RESOLUTION aspect ratio exactly so segment stills fill the
# frame without letterboxing or cropping; both dimensions are multiples of 16, which FLUX
# expects.
IMAGE_WIDTH = 1024
IMAGE_HEIGHT = 576

# The segment title/episode title are drawn as a separate text overlay at video-assembly
# time (see video.py) -- asking the image model to also render text just produces garbled
# nonsense, so it's suppressed both here and in the system prompt in prompts.py.
NEGATIVE_PROMPT = (
    "text, words, letters, writing, caption, subtitle, watermark, logo, signature, "
    "blurry, distorted, deformed, low quality, extra limbs"
)


class SegmentImagesError(Exception):
    pass


def images_for_duration(duration_seconds):
    if not duration_seconds:
        return MIN_IMAGES_PER_SEGMENT
    count = round(duration_seconds / SECONDS_PER_IMAGE)
    return max(MIN_IMAGES_PER_SEGMENT, min(MAX_IMAGES_PER_SEGMENT, count))


def _seed_for(slug, segment_number, index):
    digest = hashlib.sha256(f"{slug}:{segment_number}:{index}".encode("utf-8")).hexdigest()
    return int(digest[:8], 16)


def _propose_prompts(ollama_url, model, domain, seg, script_text, count):
    system = prompts.build_image_prompts_system(domain)
    user = prompts.build_image_prompts_user(seg["title"], seg.get("summary", ""), script_text)
    tool = prompts.build_image_prompts_tool(count)

    try:
        args = ollama_client.chat_tool(ollama_url, model, system, user, tool, temperature=0.7)
        cleaned = [str(p).strip() for p in (args.get("prompts") or []) if str(p).strip()]
    except Exception as e:  # noqa: BLE001 - a prompt-design failure must not abort the segment
        print(f"     [warn] image prompt design failed, using title-based fallback: {e}")
        cleaned = []

    if len(cleaned) < count:
        fallback = f"{seg['title']}, {prompts.DOMAINS[domain]['image_style']}"
        cleaned += [fallback] * (count - len(cleaned))
    return cleaned[:count]


def generate_for_segment(ollama_url, model, comfyui_url, domain, seg, script_text, slug, paths, force=False):
    """Generate (or reuse the cached) sequence of images for one completed segment.

    Returns (rel_paths, image_prompts, changed) -- rel_paths and image_prompts are meant
    to be stored on the segment dict as seg["images"] / seg["image_prompts"]; changed is
    True if anything was actually (re)generated, so the caller knows whether the
    segment's now-stale per-segment video needs to be rebuilt.
    """
    n = seg["number"]
    images_dir = paths["images"]
    count = images_for_duration(seg.get("duration"))

    existing = seg.get("images") or []
    existing_prompts = seg.get("image_prompts") or []
    if not force and len(existing) == count and len(existing_prompts) == count and all(
        os.path.exists(os.path.join(paths["root"], p)) and os.path.getsize(os.path.join(paths["root"], p)) > 0
        for p in existing
    ):
        return existing, existing_prompts, False

    seg_prompts = existing_prompts
    if force or len(seg_prompts) != count:
        seg_prompts = _propose_prompts(ollama_url, model, domain, seg, script_text, count)

    style_suffix = prompts.DOMAINS[domain]["image_style"]
    rel_paths = []
    changed = False
    for i, scene in enumerate(seg_prompts):
        out_path = os.path.join(images_dir, f"{n:03d}_{i:02d}.png")
        rel_path = os.path.relpath(out_path, paths["root"])
        if force or not (os.path.exists(out_path) and os.path.getsize(out_path) > 0):
            print(f"     Generating image {i + 1}/{count}...")
            full_prompt = f"{scene}, {style_suffix}"
            seed = _seed_for(slug, n, i)
            image_bytes = image_client.generate_image(
                comfyui_url, full_prompt, NEGATIVE_PROMPT, IMAGE_WIDTH, IMAGE_HEIGHT, seed,
            )
            with open(out_path, "wb") as f:
                f.write(image_bytes)
            changed = True
        rel_paths.append(rel_path)

    return rel_paths, seg_prompts, changed
