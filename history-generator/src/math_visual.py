"""Animated mathematics backgrounds: deterministic per-episode selection and rendering.

Unlike the ambient audio bed (ambient.py), which asks the LLM to design parameters, the
visual here is picked by a plain seeded random choice -- deterministic per episode slug,
same spirit as music.py's track selection -- and rendered entirely with ffmpeg's `geq`
(generic-equation) video filter: each output pixel's r/g/b is computed directly from a
math expression of its position (X, Y) and the frame's time T, no external rendering
library, no per-frame image generation in Python. A short (~20s) clip is rendered once
per episode and looped (`-stream_loop -1`, in video.py) to cover the whole runtime;
every animation's temporal frequencies are chosen as integer multiples of one cycle per
loop, so the clip's last frame's phase exactly matches its first frame's and looping
never shows a jump.
"""

import hashlib
import math
import random
import subprocess

FAMILIES = ("waves", "fourier", "trace")
# "images" (AI-generated per-segment stills, cross-faded -- see segment_images.py and
# video.py) and "thumbnail" (one AI-generated still for the whole episode, reused as a
# constant background for every segment -- see episode_thumbnail.py and video.py) live in
# this enum too, rather than separate ones, so every caller (api.py's JobRequest,
# main.py's --visual-style, the Configuration UI) keeps validating against one single
# source of truth for "what is a valid visual_style" instead of several.
VALID_VISUAL_STYLES = ("static", "math", "images", "thumbnail")
DEFAULT_VISUAL_STYLE = "static"
DEFAULT_LOOP_SECONDS = 20.0

# ffmpeg's geq filter evaluates its expression per pixel per frame in an interpreted
# expression engine -- at the pipeline's full 1920x1080 output resolution, a single
# 20s/30fps loop was measured taking 8+ minutes (and rising) per family, which is not a
# viable one-time-per-episode cost. Rendering at a quarter of that resolution instead
# (exact 4x integer scale, so upscaling stays clean) cuts render time to single-digit to
# ~25 seconds; the caller (video.py) scales the result up to the pipeline's real
# resolution when compositing. A soft, blurred-on-upscale background is not a problem --
# the whole point is a calm, non-distracting layer, not a sharp foreground element.
RENDER_RESOLUTION = "480x270"

# Dark-background-friendly accent palette, in the same spirit as video.py's SEGMENT_COLOR
# (0xE8B94A) -- muted enough not to fight with the narration title text drawn on top.
PALETTE = [
    (232, 185, 74),   # gold (matches video.py's SEGMENT_COLOR)
    (122, 178, 211),  # soft blue
    (149, 199, 148),  # soft green
    (204, 132, 163),  # muted rose
    (167, 139, 214),  # soft violet
]
BG_RGB = (20, 20, 20)  # matches video.py's BG_COLOR (0x141414)


class MathVisualError(Exception):
    pass


def _run(cmd):
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise MathVisualError(f"command failed: {' '.join(cmd)}\n{result.stderr[-2000:]}")


def validate_visual_style(value):
    v = str(value or DEFAULT_VISUAL_STYLE).strip().lower()
    if v not in VALID_VISUAL_STYLES:
        raise MathVisualError(f"visual_style must be one of {VALID_VISUAL_STYLES}, got {value!r}")
    return v


# --- Deterministic per-episode selection ------------------------------------------------

def _random_waves_params(rng):
    n_curves = rng.randint(2, 3)
    y_slots = [0.3, 0.5, 0.7] if n_curves == 3 else [0.35, 0.65]
    colors = rng.sample(PALETTE, n_curves)
    curves = []
    for i in range(n_curves):
        curves.append({
            "y0": y_slots[i],
            "amp": round(rng.uniform(0.05, 0.10), 3),
            "freq": rng.randint(2, 4),
            "cycles": rng.choice([-2, -1, 1, 2]),
            "color": list(colors[i]),
            "thickness": rng.randint(3, 5),
        })
    return {"curves": curves}


def _random_fourier_params(rng):
    return {
        "wave_type": rng.choice(["square", "sawtooth"]),
        "harmonics": rng.randint(4, 6),
        "freq": rng.randint(1, 2),
        "cycles": rng.choice([-2, -1, 1, 2]),
        "amp": round(rng.uniform(0.18, 0.28), 3),
        "color": list(rng.choice(PALETTE)),
        "thickness": rng.randint(3, 5),
    }


def _random_trace_params(rng):
    ratios = [(3, 2), (5, 4), (2, 1), (3, 1), (4, 3)]
    a, b = rng.choice(ratios)
    return {
        "a": a,
        "b": b,
        "delta": round(rng.uniform(0, 2 * math.pi), 4),
        "amp_x": round(rng.uniform(0.30, 0.38), 3),
        "amp_y": round(rng.uniform(0.30, 0.38), 3),
        "trail_points": 6,
        "dot_radius": rng.randint(5, 8),
        "trail_span_seconds": round(rng.uniform(0.8, 1.6), 2),
        "color": list(rng.choice(PALETTE)),
    }


_PARAM_BUILDERS = {
    "waves": _random_waves_params,
    "fourier": _random_fourier_params,
    "trace": _random_trace_params,
}


def select_visual(seed):
    """Deterministically pick a visualization family and its parameters from `seed`
    (the episode slug). Same seed always yields the same selection -- resuming or
    rebuilding an episode reproduces the same background without re-rolling it.
    """
    digest = hashlib.sha256(str(seed).encode("utf-8")).digest()
    rng = random.Random(digest)
    family = rng.choice(FAMILIES)
    params = _PARAM_BUILDERS[family](rng)
    return {"family": family, "params": params, "seed": str(seed)}


# --- Rendering --------------------------------------------------------------------------

def _curve_channel_exprs(y_expr, thickness, color):
    cond = f"lt(abs(Y-{y_expr}),{thickness})"
    return cond, color


def _waves_exprs(params, loop_seconds):
    exprs = {"r": str(BG_RGB[0]), "g": str(BG_RGB[1]), "b": str(BG_RGB[2])}
    for curve in params["curves"]:
        y_expr = (
            f"(H*{curve['y0']}+H*{curve['amp']}*sin(2*PI*("
            f"{curve['freq']}*X/W+{curve['cycles']}*T/{loop_seconds:.3f})))"
        )
        cond = f"lt(abs(Y-{y_expr}),{curve['thickness']})"
        for ch, idx in (("r", 0), ("g", 1), ("b", 2)):
            exprs[ch] = f"if({cond},{curve['color'][idx]},{exprs[ch]})"
    return exprs["r"], exprs["g"], exprs["b"]


def _fourier_sum_expr(wave_type, harmonics, freq, cycles, loop_seconds):
    terms = []
    for k in range(1, harmonics + 1):
        if wave_type == "square":
            n = 2 * k - 1
            coef = 4.0 / (math.pi * n)
        else:  # sawtooth
            n = k
            coef = (2.0 / math.pi) * ((-1) ** (k + 1)) / n
        terms.append(f"{coef:.6f}*sin({n}*2*PI*({freq}*X/W+{cycles}*T/{loop_seconds:.3f}))")
    return "(" + "+".join(terms) + ")"


def _fourier_exprs(params, loop_seconds):
    sum_expr = _fourier_sum_expr(
        params["wave_type"], params["harmonics"], params["freq"], params["cycles"], loop_seconds,
    )
    y_expr = f"(H*0.5+H*{params['amp']}*{sum_expr})"
    cond = f"lt(abs(Y-{y_expr}),{params['thickness']})"
    exprs = {}
    for ch, idx in (("r", 0), ("g", 1), ("b", 2)):
        exprs[ch] = f"if({cond},{params['color'][idx]},{BG_RGB[idx]})"
    return exprs["r"], exprs["g"], exprs["b"]


def _trace_exprs(params, loop_seconds):
    a, b, delta = params["a"], params["b"], params["delta"]
    amp_x, amp_y = params["amp_x"], params["amp_y"]
    trail = params["trail_points"]
    radius = params["dot_radius"]
    color = params["color"]
    trail_span = params["trail_span_seconds"]

    terms = {"r": [], "g": [], "b": []}
    for k in range(trail):
        weight = (trail - k) / trail
        dt = k * (trail_span / trail)
        tt = f"mod(T-{dt:.4f}+{loop_seconds:.3f},{loop_seconds:.3f})"
        x_expr = f"(W*0.5+W*{amp_x}*sin({a}*2*PI*{tt}/{loop_seconds:.3f}+{delta:.4f}))"
        y_expr = f"(H*0.5+H*{amp_y}*sin({b}*2*PI*{tt}/{loop_seconds:.3f}))"
        dist = f"hypot(X-{x_expr},Y-{y_expr})"
        dot_r = max(2.0, radius * (0.5 + 0.5 * weight))
        lit = f"(if(lt({dist},{dot_r:.2f}),{weight:.3f},0))"
        for ch, idx in (("r", 0), ("g", 1), ("b", 2)):
            terms[ch].append(f"{lit}*{color[idx]}")

    exprs = {}
    for ch, idx in (("r", 0), ("g", 1), ("b", 2)):
        exprs[ch] = f"min(255,{BG_RGB[idx]}+{'+'.join(terms[ch])})"
    return exprs["r"], exprs["g"], exprs["b"]


_EXPR_BUILDERS = {
    "waves": _waves_exprs,
    "fourier": _fourier_exprs,
    "trace": _trace_exprs,
}


def render_loop(visual, resolution, fps, loop_seconds, out_path):
    """Render `visual` (as returned by select_visual) into a loop_seconds-long, seamlessly
    loopable video clip at out_path. No audio track -- this is a silent background layer,
    mixed with narration/music/ambient entirely separately in video.py.
    """
    family = visual["family"]
    builder = _EXPR_BUILDERS.get(family)
    if builder is None:
        raise MathVisualError(f"unknown math visual family: {family!r}")
    r_expr, g_expr, b_expr = builder(visual["params"], loop_seconds)

    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"color=c=black:s={resolution}:r={fps}:d={loop_seconds:.3f}",
        "-vf", f"format=rgba,geq=r='{r_expr}':g='{g_expr}':b='{b_expr}':a=255,format=yuv420p",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-t", f"{loop_seconds:.3f}",
        out_path,
    ]
    _run(cmd)
    return out_path
