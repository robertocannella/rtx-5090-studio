"""One AI-generated image for the whole episode (visual_style="thumbnail"), reused as a
constant background for every segment -- unlike visual_style="images" (segment_images.py),
which generates several images per segment and cross-fades between them.

Generated once per episode: an Ollama tool call proposes one vivid scene description
representing the episode's overall topic (not any single segment), then ComfyUI renders it
via FLUX.1-schnell (see image_client.py). Both go through gpu_lock so they never run at
the same time as anything else touching the GPU (see gpu_lock.py).

Caching follows the same one-time-choice philosophy as math_visual.select_visual(): the
caller (pipeline.py:apply_thumbnail_to_episode) only calls generate() the first time
visual_style becomes "thumbnail" for this episode, then reuses the cached path on every
subsequent run -- this module does no existence-checking of its own, since (unlike
segment_images.py, where the right image *count* depends on each segment's narration
duration and can change across runs) there is exactly one image, generated exactly once.
"""

import os

import image_client
import ollama_client
import prompts

# Same aspect ratio and resolution as segment_images.py's per-segment stills, for the same
# reason: matches video.py's RESOLUTION aspect ratio exactly (no letterboxing/cropping
# beyond the scale+crop video.py already does to fill the frame), and both dimensions are
# multiples of 16, which FLUX expects.
IMAGE_WIDTH = 1024
IMAGE_HEIGHT = 576

# The title-card text is drawn as a separate overlay at video-assembly time (see
# video.py) -- asking the image model to also render text just produces garbled nonsense.
NEGATIVE_PROMPT = (
    "text, words, letters, writing, caption, subtitle, watermark, logo, signature, "
    "blurry, distorted, deformed, low quality, extra limbs"
)

THUMBNAIL_FILENAME = "thumbnail.png"


class EpisodeThumbnailError(Exception):
    pass


def _propose_prompt(ollama_url, model, domain, topic, title):
    system = prompts.build_thumbnail_prompt_system(domain)
    user = prompts.build_thumbnail_prompt_user(topic, title)
    tool = prompts.build_thumbnail_prompt_tool()

    try:
        args = ollama_client.chat_tool(ollama_url, model, system, user, tool, temperature=0.7)
        scene = str(args.get("prompt") or "").strip()
    except Exception as e:  # noqa: BLE001 - a prompt-design failure must not abort the episode
        print(f"     [warn] thumbnail prompt design failed, using topic-based fallback: {e}")
        scene = ""

    return scene or title or topic


def generate(ollama_url, model, comfyui_url, domain, topic, title, paths):
    """Generates the one whole-episode thumbnail image and returns (rel_path, prompt) --
    rel_path is relative to paths["root"] (the episode root), meant to be stored as
    manifest["thumbnail_image"]; prompt is stored as manifest["thumbnail_prompt"], mainly
    for debugging/inspection.
    """
    scene = _propose_prompt(ollama_url, model, domain, topic, title)
    style_suffix = prompts.DOMAINS[domain]["image_style"]
    full_prompt = f"{scene}, {style_suffix}"

    out_path = os.path.join(paths["images"], THUMBNAIL_FILENAME)
    print(f"     Generating episode thumbnail: {scene}")
    image_bytes = image_client.generate_image(comfyui_url, full_prompt, NEGATIVE_PROMPT, IMAGE_WIDTH, IMAGE_HEIGHT)
    with open(out_path, "wb") as f:
        f.write(image_bytes)

    rel_path = os.path.relpath(out_path, paths["root"])
    return rel_path, scene
