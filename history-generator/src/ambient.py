"""Procedurally-synthesized ambient background audio, designed by the LLM.

There's no library of recorded/licensed ambient music anywhere in this stack, so the
"instrument" here is ffmpeg itself: a small stack of oscillators (a drone plus a soft
chord), filtered noise, a slow tremolo, and an echo. design() asks the model, via a real
Ollama tool call, to act as a sound designer and pick parameters for that synth chain
based on the episode's topic; render() turns those parameters into an actual audio file.
"""

import subprocess

import ollama_client

SAMPLE_RATE = 48000

AMBIENT_SYSTEM = (
    "You are a sound designer choosing a procedurally-synthesized ambient background "
    "audio bed for a narrated educational video. There are no real instruments or recordings "
    "available -- the bed is built entirely from sine/triangle drones, filtered noise, a "
    "slow tremolo, and echo -- so choose parameters for that synth chain (not real-world "
    "instrument names) that will read as a mood fitting the topic when rendered. It plays "
    "continuously under narration for the whole episode, so keep it subtle and non-busy: "
    "a quiet, slowly-moving pad, not a melody. You must call design_ambient_bed."
)

AMBIENT_TOOL = {
    "type": "function",
    "function": {
        "name": "design_ambient_bed",
        "description": (
            "Design a procedurally-synthesized ambient background audio bed matching the "
            "mood of a history video's topic. Rendered from oscillators and filtered noise, "
            "then mixed quietly under the narration."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "mood": {
                    "type": "string",
                    "description": "Short label for the mood, e.g. 'epic and triumphant' or 'somber and reflective'.",
                },
                "base_freq_hz": {
                    "type": "number",
                    "description": "Fundamental drone frequency in Hz. Lower (50-100) feels heavier/darker, higher (150-300) feels lighter/brighter.",
                    "minimum": 40,
                    "maximum": 400,
                },
                "waveform": {
                    "type": "string",
                    "enum": ["sine", "triangle"],
                    "description": "Oscillator shape for the drone. Sine is smoother/warmer, triangle is slightly richer/buzzier.",
                },
                "chord_intervals": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "minItems": 1,
                    "maxItems": 4,
                    "description": "Semitone offsets from base_freq_hz stacked as a soft pad, e.g. [0, 7, 12] for a fifth and octave above the root.",
                },
                "noise_color": {
                    "type": "string",
                    "enum": ["none", "white", "pink", "brown"],
                    "description": "Texture bed under the drone. 'brown' is a deep rumble, 'pink' is soft airy hiss, 'white' is harsher static, 'none' skips it.",
                },
                "noise_level_db": {
                    "type": "number",
                    "description": "Level of the noise bed in dBFS (negative). -40 is barely audible, -18 is prominent.",
                    "minimum": -50,
                    "maximum": -10,
                },
                "filter_cutoff_hz": {
                    "type": "number",
                    "description": "Lowpass filter cutoff for the whole bed. Lower (200-500) sounds dark/muffled/ominous, higher (1500-4000) sounds open/airy.",
                    "minimum": 150,
                    "maximum": 5000,
                },
                "tremolo_rate_hz": {
                    "type": "number",
                    "description": "Speed of slow volume pulsing/swelling in Hz. Very slow (0.05-0.15) for gentle breathing pads, faster (0.3-0.8) for tense pulsing.",
                    "minimum": 0.02,
                    "maximum": 1.0,
                },
                "tremolo_depth": {
                    "type": "number",
                    "description": "Depth of the tremolo pulsing, 0 (none) to 1 (strong).",
                    "minimum": 0,
                    "maximum": 1,
                },
                "reverb_amount": {
                    "type": "number",
                    "description": "Amount of echo/space applied, 0 (dry/close) to 1 (huge/cavernous).",
                    "minimum": 0,
                    "maximum": 1,
                },
                "bed_level_db": {
                    "type": "number",
                    "description": "Overall level of the ambient bed relative to full scale, in dBFS (negative -- it must sit quietly under narration). Typical -24 to -14.",
                    "minimum": -35,
                    "maximum": -8,
                },
            },
            "required": [
                "mood", "base_freq_hz", "waveform", "chord_intervals", "noise_color",
                "noise_level_db", "filter_cutoff_hz", "tremolo_rate_hz", "tremolo_depth",
                "reverb_amount", "bed_level_db",
            ],
        },
    },
}

DEFAULT_PARAMS = {
    "mood": "neutral",
    "base_freq_hz": 110,
    "waveform": "sine",
    "chord_intervals": [0, 7],
    "noise_color": "pink",
    "noise_level_db": -32,
    "filter_cutoff_hz": 1200,
    "tremolo_rate_hz": 0.1,
    "tremolo_depth": 0.3,
    "reverb_amount": 0.3,
    "bed_level_db": -20,
}


class AmbientError(Exception):
    pass


def _run(cmd):
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise AmbientError(f"command failed: {' '.join(cmd)}\n{result.stderr[-2000:]}")


def _clamp(value, lo, hi, default):
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, v))


def _validate(args):
    p = dict(DEFAULT_PARAMS)
    p["mood"] = str(args.get("mood") or p["mood"])[:80]
    p["base_freq_hz"] = _clamp(args.get("base_freq_hz"), 40, 400, p["base_freq_hz"])
    p["waveform"] = args.get("waveform") if args.get("waveform") in ("sine", "triangle") else p["waveform"]

    intervals = args.get("chord_intervals")
    if isinstance(intervals, list) and intervals:
        cleaned = []
        for v in intervals[:4]:
            try:
                cleaned.append(int(_clamp(v, -24, 36, 0)))
            except (TypeError, ValueError):
                continue
        if cleaned:
            p["chord_intervals"] = cleaned

    p["noise_color"] = args.get("noise_color") if args.get("noise_color") in ("none", "white", "pink", "brown") else p["noise_color"]
    p["noise_level_db"] = _clamp(args.get("noise_level_db"), -50, -10, p["noise_level_db"])
    p["filter_cutoff_hz"] = _clamp(args.get("filter_cutoff_hz"), 150, 5000, p["filter_cutoff_hz"])
    p["tremolo_rate_hz"] = _clamp(args.get("tremolo_rate_hz"), 0.02, 1.0, p["tremolo_rate_hz"])
    p["tremolo_depth"] = _clamp(args.get("tremolo_depth"), 0, 1, p["tremolo_depth"])
    p["reverb_amount"] = _clamp(args.get("reverb_amount"), 0, 1, p["reverb_amount"])
    p["bed_level_db"] = _clamp(args.get("bed_level_db"), -35, -8, p["bed_level_db"])
    return p


def design(ollama_url, model, topic, title):
    user = (
        f"Episode topic: {topic}\n"
        f"Episode title: {title}\n\n"
        "Design an ambient background bed that fits this episode's mood."
    )
    try:
        args = ollama_client.chat_tool(ollama_url, model, AMBIENT_SYSTEM, user, AMBIENT_TOOL)
        params = _validate(args)
        print(f"     Mood: {params['mood']}")
        return params
    except Exception as e:  # noqa: BLE001 - ambient design must not abort the run
        print(f"     [warn] ambient design failed, using neutral fallback: {e}")
        return dict(DEFAULT_PARAMS)


def _osc_source(freq, waveform):
    freq = max(20.0, float(freq))
    if waveform == "triangle":
        expr = f"(2/PI)*asin(sin(2*PI*{freq}*t))"
        return f"aevalsrc=exprs='{expr}':sample_rate={SAMPLE_RATE}"
    return f"sine=frequency={freq}:sample_rate={SAMPLE_RATE}"


def render(params, duration_seconds, out_path):
    """Synthesize params into an audio file of exactly duration_seconds."""
    duration_seconds = max(1.0, float(duration_seconds))
    base = params["base_freq_hz"]
    waveform = params["waveform"]
    intervals = params["chord_intervals"]

    inputs = []
    osc_labels = []
    for i, semis in enumerate(intervals):
        freq = base * (2 ** (semis / 12.0))
        inputs += ["-f", "lavfi", "-i", _osc_source(freq, waveform)]
        osc_labels.append(f"[{i}:a]")

    noise_idx = None
    if params["noise_color"] != "none":
        noise_idx = len(intervals)
        inputs += ["-f", "lavfi", "-i", f"anoisesrc=color={params['noise_color']}:sample_rate={SAMPLE_RATE}:amplitude=1.0"]

    filters = []
    if len(osc_labels) > 1:
        filters.append("".join(osc_labels) + f"amix=inputs={len(osc_labels)}:normalize=0:duration=longest[pad]")
    else:
        filters.append(f"{osc_labels[0]}anull[pad]")
    bed_label = "[pad]"

    if noise_idx is not None:
        filters.append(f"[{noise_idx}:a]volume={params['noise_level_db']}dB[noise]")
        filters.append(f"{bed_label}[noise]amix=inputs=2:normalize=0:duration=longest[bed0]")
        bed_label = "[bed0]"

    filters.append(f"{bed_label}lowpass=f={params['filter_cutoff_hz']}[bed1]")
    tremolo_rate = max(0.1, min(20000.0, float(params["tremolo_rate_hz"])))
    filters.append(f"[bed1]tremolo=f={tremolo_rate}:d={params['tremolo_depth']}[bed2]")
    ### EDIITED -RCAN
    ###filters.append(f"[bed1]tremolo=f={params['tremolo_rate_hz']}:d={params['tremolo_depth']}[bed2]")
    bed_label = "[bed2]"

    if params["reverb_amount"] > 0.05:
        r = params["reverb_amount"]
        out_gain = round(0.3 + 0.5 * r, 3)
        decay1 = round(0.25 * r, 3)
        decay2 = round(0.15 * r, 3)
        filters.append(f"{bed_label}aecho=0.9:{out_gain}:1000|1800:{decay1}|{decay2}[bed3]")
        bed_label = "[bed3]"

    filters.append(f"{bed_label}volume={params['bed_level_db']}dB[out]")

    cmd = [
        "ffmpeg", "-y",
        *inputs,
        "-filter_complex", ";".join(filters),
        "-map", "[out]",
        "-t", f"{duration_seconds:.2f}",
        "-c:a", "pcm_s16le",
        out_path,
    ]
    _run(cmd)
    return out_path
