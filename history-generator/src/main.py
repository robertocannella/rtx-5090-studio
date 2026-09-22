import argparse
import os
import sys

import math_visual
import music
import pipeline
import prompts
import sentence_gap
import video


def _env_bool(name, default):
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() not in ("0", "false", "no", "")


def parse_args(argv):
    p = argparse.ArgumentParser(description="Generate an educational history video episode.")
    p.add_argument("topic", help="Episode topic, e.g. 'Ancient Rome'")
    p.add_argument(
        "--duration", type=int, default=int(os.environ.get("TARGET_DURATION", 3600)),
        help="Target narration duration in seconds (default: 3600)",
    )
    p.add_argument(
        "--voice", default=os.environ.get("KOKORO_VOICE", "af_heart"),
        help="Kokoro voice (default: af_heart)",
    )
    p.add_argument(
        "--speed", type=float, default=float(os.environ.get("KOKORO_SPEED", 1.0)),
        help="Kokoro narration speed, e.g. 0.8 = slower, 1.25 = faster (default: 1.0)",
    )
    p.add_argument(
        "--ambient", dest="ambient", action="store_true",
        default=_env_bool("AMBIENT_ENABLED", True),
        help="Generate a procedural ambient background bed, mood chosen by the model from the topic (default: on)",
    )
    p.add_argument("--no-ambient", dest="ambient", action="store_false", help="Disable the ambient background bed")
    p.add_argument(
        "--youtube-metadata", dest="youtube_metadata", action="store_true",
        default=_env_bool("YOUTUBE_METADATA_ENABLED", True),
        help=(
            "Generate YouTube upload metadata (title, description, tags, category, and "
            "chapter timestamps computed from segment durations) from the finished "
            "script once narration completes (default: on)"
        ),
    )
    p.add_argument(
        "--no-youtube-metadata", dest="youtube_metadata", action="store_false",
        help="Disable YouTube metadata generation",
    )
    p.add_argument(
        "--pitch", dest="pitch_semitones", type=float,
        default=float(os.environ.get("PITCH_SEMITONES", 0.0)),
        help=(
            "Narrator pitch shift in semitones, -4.0 to +4.0 (0 = original Kokoro voice; "
            "-2 noticeably deeper, -1 slightly deeper, +1 slightly higher, +2 noticeably "
            "higher). Speaking speed/duration is unaffected. Default: 0.0"
        ),
    )
    p.add_argument(
        "--music", dest="music", action="store_true",
        default=_env_bool("MUSIC_ENABLED", False),
        help="Mix in background music selected from the local library (default: off)",
    )
    p.add_argument("--no-music", dest="music", action="store_false", help="Disable background music")
    p.add_argument(
        "--music-mood", default=os.environ.get("MUSIC_MOOD", "sleep-ambient"),
        help="Catalog category/tag used for automatic track selection (default: sleep-ambient)",
    )
    p.add_argument(
        "--music-track-id", default=os.environ.get("MUSIC_TRACK_ID") or None,
        help="Exact catalog.json track id; overrides mood-based auto-selection and its safety filters",
    )
    p.add_argument(
        "--music-level", dest="music_level_db", type=float,
        default=float(os.environ.get("MUSIC_LEVEL_DB", -25.0)),
        help=f"Background music level in dBFS, {music.MIN_LEVEL_DB} to {music.MAX_LEVEL_DB} (default: -25.0)",
    )
    p.add_argument(
        "--music-fade-in", dest="music_fade_in_seconds", type=float,
        default=float(os.environ.get("MUSIC_FADE_IN_SECONDS", 8.0)),
        help="Music fade-in duration in seconds (default: 8.0)",
    )
    p.add_argument(
        "--music-fade-out", dest="music_fade_out_seconds", type=float,
        default=float(os.environ.get("MUSIC_FADE_OUT_SECONDS", 20.0)),
        help="Music fade-out duration in seconds (default: 20.0)",
    )
    p.add_argument(
        "--music-library-dir", default=os.environ.get("MUSIC_LIBRARY_DIR", "/app/audio-library/music"),
        help="Path to the local music library and its catalog.json (default: /app/audio-library/music)",
    )
    p.add_argument(
        "--segment-gap", dest="segment_gap_seconds", type=float,
        default=float(os.environ.get("SEGMENT_GAP_SECONDS", video.DEFAULT_GAP_SECONDS)),
        help=(
            f"Silent pause inserted between segments, in seconds, {video.MIN_GAP_SECONDS} to "
            f"{video.MAX_GAP_SECONDS} (0 disables it). Background music/ambient keep playing "
            f"through the pause; narration itself is never split mid-sentence. Default: {video.DEFAULT_GAP_SECONDS}"
        ),
    )
    p.add_argument(
        "--sentence-gap", dest="sentence_gap_seconds", type=float,
        default=float(os.environ.get("SENTENCE_GAP_SECONDS", sentence_gap.DEFAULT_SENTENCE_GAP_SECONDS)),
        help=(
            f"Pause inserted between sentences within a segment, in seconds, "
            f"{sentence_gap.MIN_SENTENCE_GAP_SECONDS} to {sentence_gap.MAX_SENTENCE_GAP_SECONDS} "
            f"(0 disables it, synthesizing the whole segment in one Kokoro call as before). "
            f"Default: {sentence_gap.DEFAULT_SENTENCE_GAP_SECONDS}"
        ),
    )
    p.add_argument(
        "--visual-style", choices=math_visual.VALID_VISUAL_STYLES,
        default=os.environ.get("VISUAL_STYLE", math_visual.DEFAULT_VISUAL_STYLE),
        help=(
            "Segment video background: 'static' (default) is the plain dark background "
            "with title text; 'math' selects one animated mathematical visualization "
            "(sine/cosine waves, a Fourier-series approximation, or a traced parametric "
            "curve) at random -- deterministic and stable per episode, reproduced on "
            "resume, only re-rolled by --force; 'images' generates several AI "
            "illustrations per segment (via Ollama for scene prompts and ComfyUI/FLUX "
            "for rendering) and cross-fades between them, cached per segment and only "
            "regenerated when missing or --force'd."
        ),
    )
    p.add_argument(
        "--domain", choices=sorted(prompts.DOMAINS), default=os.environ.get("DOMAIN", prompts.DEFAULT_DOMAIN),
        help=(
            "Content domain -- which system/segment prompts and outline guidance to use. "
            "'history' (default): past events/people/inventions. 'math': mathematical "
            "results and concepts, explained without symbolic notation (audio-only). "
            "'discovery': present-tense science/how-things-work explainers (not history, "
            "not news). Chosen once per episode like the topic itself; changing it on a "
            "resumed episode is ignored (use --force to start over under a new domain)."
        ),
    )
    p.add_argument("--force", action="store_true", help="Regenerate the episode from scratch")
    p.add_argument("--model", default=os.environ.get("OLLAMA_MODEL", "qwen3:32b"))
    p.add_argument("--ollama-url", default=os.environ.get("OLLAMA_URL", "http://ollama:11434"))
    p.add_argument("--kokoro-url", default=os.environ.get("KOKORO_URL", "http://kokoro:8880"))
    p.add_argument("--comfyui-url", default=os.environ.get("COMFYUI_URL", "http://comfyui:8188"))
    p.add_argument("--output-dir", default=os.environ.get("OUTPUT_DIR", "/app/output"))
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv if argv is not None else sys.argv[1:])
    result = pipeline.run(args)
    if result is None:
        sys.exit(1)

    completed = [s for s in result["manifest"]["segments"] if s["status"] == "complete"]
    print()
    print("Done.")
    print(f"Domain: {result['manifest'].get('domain', prompts.DEFAULT_DOMAIN)}")
    print(f"Episode dir: {result['paths']['root']}")
    print(f"Segments completed: {len(completed)} of {len(result['manifest']['segments'])} outlined")
    if result["failed"]:
        print(f"Segments failed: {len(result['failed'])} -> " + ", ".join(f"#{s['number']}" for s in result["failed"]))
    print(f"Narration duration: {result['narration_seconds']:.1f} sec")
    visual = result["manifest"].get("visual")
    if result["manifest"].get("visual_style") == "math" and visual:
        print(f"Visual: {visual['family']}")
    youtube = result["manifest"].get("youtube")
    if youtube:
        print(f"YouTube title: {youtube['title']}")
        print(f"YouTube metadata: {result['paths']['manifest']} (\"youtube\" key)")
    print(f"Final MP4: {result['final_path']}")


if __name__ == "__main__":
    main()
