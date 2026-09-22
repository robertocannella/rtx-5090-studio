"""Client for ComfyUI's HTTP API, generating one FLUX.1-schnell image per call.

Mirrors kokoro_client.py's shape (a thin synchronous wrapper with retry/backoff), but
ComfyUI's API is a submit-then-poll job queue rather than a single blocking request:
POST /prompt queues a node-graph workflow and returns a prompt_id immediately, then
/history/{prompt_id} is polled until that id appears with a "success" status, and the
resulting PNG bytes are fetched from /view. The exact node graph below (UNETLoader ->
DualCLIPLoader -> VAELoader -> CLIPTextEncode x2 -> EmptySD3LatentImage -> KSampler ->
VAEDecode -> SaveImage) and every input field name were verified live against a running
ComfyUI instance's /object_info/{NodeName} before being hand-written here, not guessed
from memory or documentation -- ComfyUI silently rejects unknown fields with a 400 and
node_errors, so a wrong field name fails loud at submit time, not at image-fetch time.
"""

import time
import uuid

import requests

from gpu_lock import gpu_lock

UNET_NAME = "flux1-schnell-fp8.safetensors"
CLIP_NAME1 = "clip_l.safetensors"
CLIP_NAME2 = "t5xxl_fp8_e4m3fn.safetensors"
VAE_NAME = "ae.safetensors"

# schnell is a distilled, few-step model -- cfg=1.0/steps=4 is the model card's own
# recommendation; higher cfg or more steps doesn't improve schnell output and can hurt it
# (it wasn't trained for classifier-free guidance the way the full dev/pro models were).
DEFAULT_STEPS = 4
DEFAULT_CFG = 1.0
SAMPLER_NAME = "euler"
SCHEDULER = "simple"


class ImageError(Exception):
    pass


def _build_workflow(prompt, negative_prompt, width, height, seed, steps, cfg):
    return {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": UNET_NAME, "weight_dtype": "fp8_e4m3fn"}},
        "2": {"class_type": "DualCLIPLoader", "inputs": {"clip_name1": CLIP_NAME1, "clip_name2": CLIP_NAME2, "type": "flux"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": VAE_NAME}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["2", 0]}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {"text": negative_prompt, "clip": ["2", 0]}},
        "6": {"class_type": "EmptySD3LatentImage", "inputs": {"width": width, "height": height, "batch_size": 1}},
        "7": {"class_type": "KSampler", "inputs": {
            "model": ["1", 0], "seed": seed, "steps": steps, "cfg": cfg,
            "sampler_name": SAMPLER_NAME, "scheduler": SCHEDULER,
            "positive": ["4", 0], "negative": ["5", 0],
            "latent_image": ["6", 0], "denoise": 1.0,
        }},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["7", 0], "vae": ["3", 0]}},
        "9": {"class_type": "SaveImage", "inputs": {"images": ["8", 0], "filename_prefix": "historygen"}},
    }


def generate_image(
    base_url, prompt, negative_prompt="", width=1024, height=576, seed=0,
    steps=DEFAULT_STEPS, cfg=DEFAULT_CFG, retries=3, backoff=5, timeout=180, poll_interval=1.0,
):
    """Submit a single FLUX.1-schnell text-to-image job and return the resulting PNG
    bytes. Held under gpu_lock for the whole submit-to-completion window, not just the
    submit call -- the GPU is busy rendering for that entire span (see gpu_lock.py).
    """
    workflow = _build_workflow(prompt, negative_prompt, width, height, seed, steps, cfg)
    payload = {"prompt": workflow, "client_id": uuid.uuid4().hex}

    last_exc = None
    for attempt in range(1, retries + 1):
        try:
            with gpu_lock:
                resp = requests.post(f"{base_url}/prompt", json=payload, timeout=30)
                resp.raise_for_status()
                data = resp.json()
                node_errors = data.get("node_errors") or {}
                if node_errors:
                    raise ImageError(f"ComfyUI rejected workflow: {node_errors}")
                prompt_id = data["prompt_id"]
                return _wait_and_fetch(base_url, prompt_id, timeout, poll_interval)
        except Exception as e:  # noqa: BLE001 - want to retry on anything and report it
            last_exc = e
            if attempt < retries:
                sleep_s = backoff * attempt
                print(f"     [warn] ComfyUI request failed (attempt {attempt}/{retries}): {e}; retrying in {sleep_s:.0f}s")
                time.sleep(sleep_s)
    raise ImageError(f"ComfyUI request failed after {retries} attempts: {last_exc}")


def _wait_and_fetch(base_url, prompt_id, timeout, poll_interval):
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = requests.get(f"{base_url}/history/{prompt_id}", timeout=30)
        resp.raise_for_status()
        history = resp.json()
        entry = history.get(prompt_id)
        if entry:
            status = entry.get("status") or {}
            if status.get("completed"):
                images = (entry.get("outputs") or {}).get("9", {}).get("images") or []
                if not images:
                    raise ImageError(f"ComfyUI job {prompt_id} completed but produced no image output")
                img = images[0]
                return _fetch_image(base_url, img["filename"], img.get("subfolder", ""), img.get("type", "output"))
            if status.get("status_str") == "error":
                raise ImageError(f"ComfyUI job {prompt_id} failed: {status}")
        time.sleep(poll_interval)
    raise ImageError(f"ComfyUI job {prompt_id} did not complete within {timeout}s")


def free_memory(base_url, timeout=30):
    """Ask ComfyUI to unload its models and release VRAM.

    ComfyUI keeps a generation's model weights resident in VRAM afterward by default
    (fast for a burst of back-to-back generations, but FLUX's ~16GB sitting parked
    indefinitely starves Ollama's qwen3:32b of the VRAM it needs, forcing it to spill
    onto CPU and become slow enough to blow past its own request timeout -- this is
    exactly what happened in practice: ComfyUI left ~16.6GB resident from an earlier
    episode, Ollama fell back to a ~50/50 CPU/GPU split, and its next large outline
    call then exceeded ollama_client's 180s timeout on every retry). Called once per
    segment after that segment's images are generated (see
    pipeline.py:apply_images_to_segments) -- frequent enough that Ollama is never
    starved for more than one segment's worth of image generation, infrequent enough
    that the reload cost isn't paid per-image. Best-effort: a failed call here must not
    abort the episode, it just means ComfyUI stays loaded a bit longer than ideal.
    """
    try:
        with gpu_lock:
            resp = requests.post(
                f"{base_url}/free", json={"unload_models": True, "free_memory": True}, timeout=timeout,
            )
            resp.raise_for_status()
    except Exception as e:  # noqa: BLE001 - best-effort cleanup must not fail the episode
        print(f"     [warn] ComfyUI free-memory call failed (non-fatal): {e}")


def _fetch_image(base_url, filename, subfolder, image_type):
    resp = requests.get(
        f"{base_url}/view", params={"filename": filename, "subfolder": subfolder, "type": image_type}, timeout=30,
    )
    resp.raise_for_status()
    if not resp.content:
        raise ImageError("empty image response")
    return resp.content
