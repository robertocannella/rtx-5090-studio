"""Persistent HTTP API wrapping the existing history-generator pipeline.

Runs as a long-lived service (unlike the one-shot `main.py` CLI path) so it can
be triggered from Open WebUI. Background jobs run the exact same `pipeline.run`
used by the CLI, in a background thread, against the same shared output volume
and the same manifest.json files. This module adds no new generation logic —
it is purely a job-queue/status wrapper around the existing pipeline.
"""

import contextlib
import math
import os
import threading
import time
import uuid
from types import SimpleNamespace

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator

import kokoro_client
import manifest as manifest_mod
import math_visual as math_visual_mod
import music as music_mod
import notify
import pipeline
import pitch as pitch_mod
import prompts
import sentence_gap as sentence_gap_mod
import video as video_mod
import voice_samples
import youtube_metadata
import youtube_publish

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://ollama:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3:32b")
KOKORO_URL = os.environ.get("KOKORO_URL", "http://kokoro:8880")
COMFYUI_URL = os.environ.get("COMFYUI_URL", "http://comfyui:8188")
KOKORO_VOICE = os.environ.get("KOKORO_VOICE", "af_heart")
KOKORO_SPEED = float(os.environ.get("KOKORO_SPEED", 1.0))
AMBIENT_ENABLED = os.environ.get("AMBIENT_ENABLED", "true").strip().lower() not in ("0", "false", "no", "")
YOUTUBE_METADATA_ENABLED = os.environ.get("YOUTUBE_METADATA_ENABLED", "true").strip().lower() not in ("0", "false", "no", "")
MUSIC_ENABLED = os.environ.get("MUSIC_ENABLED", "false").strip().lower() not in ("0", "false", "no", "")
MUSIC_MOOD = os.environ.get("MUSIC_MOOD", "sleep-ambient")
MUSIC_LEVEL_DB = float(os.environ.get("MUSIC_LEVEL_DB", -25.0))
MUSIC_FADE_IN_SECONDS = float(os.environ.get("MUSIC_FADE_IN_SECONDS", 8.0))
MUSIC_FADE_OUT_SECONDS = float(os.environ.get("MUSIC_FADE_OUT_SECONDS", 20.0))
MUSIC_LIBRARY_DIR = os.environ.get("MUSIC_LIBRARY_DIR", "/app/audio-library/music")
SEGMENT_GAP_SECONDS = float(os.environ.get("SEGMENT_GAP_SECONDS", video_mod.DEFAULT_GAP_SECONDS))
SENTENCE_GAP_SECONDS = float(os.environ.get("SENTENCE_GAP_SECONDS", sentence_gap_mod.DEFAULT_SENTENCE_GAP_SECONDS))
VISUAL_STYLE = os.environ.get("VISUAL_STYLE", math_visual_mod.DEFAULT_VISUAL_STYLE)
DOMAIN = os.environ.get("DOMAIN", prompts.DEFAULT_DOMAIN)
OUTPUT_DIR = os.environ.get("OUTPUT_DIR", "/app/output")
# The real filesystem path `./output` (OUTPUT_DIR) is bind-mounted from on the host --
# there is no browser-facing route to these files (history-api is intentionally not on
# the edge network), so this is reported alongside the container path purely so a job's
# status can point at a path that's actually openable outside the container. Empty by
# default (no host path reported) so this is opt-in per deployment.
HOST_OUTPUT_DIR = os.environ.get("HOST_OUTPUT_DIR", "")
VOICE_SAMPLES_DIR = os.environ.get("VOICE_SAMPLES_DIR", "/app/voice_samples")
YOUTUBE_CLIENT_ID = os.environ.get("YOUTUBE_CLIENT_ID", "")
YOUTUBE_CLIENT_SECRET = os.environ.get("YOUTUBE_CLIENT_SECRET", "")
YOUTUBE_REFRESH_TOKEN = os.environ.get("YOUTUBE_REFRESH_TOKEN", "")


def _prewarm_voice_samples():
    """Best-effort: generate every known voice's preview clip once at startup so the
    Configuration UI's preview button is instant for everyone, not just whoever happens
    to click first. Sequential on purpose -- Kokoro runs on CPU (see docs) and isn't
    something we want several concurrent synthesis calls hammering at once, especially
    right at startup when a real generation job could also be starting up. Never raises:
    an unreachable Kokoro at startup (or one voice failing) must not crash the API.
    """
    try:
        voices = kokoro_client.list_voices(KOKORO_URL)
    except Exception as e:  # noqa: BLE001 - startup pre-warm must never take the API down
        print(f"[warn] voice-sample pre-warm: could not list Kokoro voices: {e}", flush=True)
        return
    warmed = 0
    for voice_id in voices:
        try:
            voice_samples.get_or_create(KOKORO_URL, voice_id, VOICE_SAMPLES_DIR)
            warmed += 1
        except Exception as e:  # noqa: BLE001 - one bad voice must not stop the rest
            print(f"[warn] voice-sample pre-warm failed for {voice_id!r}: {e}", flush=True)
    print(f"voice-sample pre-warm: {warmed}/{len(voices)} cached", flush=True)


@contextlib.asynccontextmanager
async def _lifespan(app: FastAPI):
    threading.Thread(target=_prewarm_voice_samples, daemon=True).start()
    yield


app = FastAPI(title="History Generator API", lifespan=_lifespan)

_lock = threading.Lock()
_jobs = {}  # job_id -> job dict
_active_slugs = {}  # slug -> job_id, only while queued/running


class JobRequest(BaseModel):
    topic: str
    duration: int = 3600
    voice: str = Field(default=KOKORO_VOICE)
    speed: float = Field(default=KOKORO_SPEED, ge=0.25, le=4.0)
    ambient: bool = Field(default=AMBIENT_ENABLED)
    youtube_metadata: bool = Field(default=YOUTUBE_METADATA_ENABLED)
    pitch_semitones: float = Field(default=0.0, ge=pitch_mod.MIN_SEMITONES, le=pitch_mod.MAX_SEMITONES)
    music: bool = Field(default=MUSIC_ENABLED)
    music_mood: str | None = Field(default=MUSIC_MOOD)
    music_track_id: str | None = Field(default=None)
    music_level_db: float = Field(default=MUSIC_LEVEL_DB, ge=music_mod.MIN_LEVEL_DB, le=music_mod.MAX_LEVEL_DB)
    music_fade_in_seconds: float = Field(default=MUSIC_FADE_IN_SECONDS, ge=0)
    music_fade_out_seconds: float = Field(default=MUSIC_FADE_OUT_SECONDS, ge=0)
    segment_gap_seconds: float = Field(
        default=SEGMENT_GAP_SECONDS, ge=video_mod.MIN_GAP_SECONDS, le=video_mod.MAX_GAP_SECONDS,
    )
    sentence_gap_seconds: float = Field(
        default=SENTENCE_GAP_SECONDS,
        ge=sentence_gap_mod.MIN_SENTENCE_GAP_SECONDS, le=sentence_gap_mod.MAX_SENTENCE_GAP_SECONDS,
    )
    visual_style: str = Field(default=VISUAL_STYLE)
    domain: str = Field(default=DOMAIN)
    force: bool = False
    model: str = Field(default=OLLAMA_MODEL)

    @field_validator(
        "pitch_semitones", "music_level_db", "music_fade_in_seconds", "music_fade_out_seconds",
        "segment_gap_seconds", "sentence_gap_seconds",
    )
    @classmethod
    def _finite(cls, v):
        if not math.isfinite(v):
            raise ValueError("must be finite")
        return v

    @field_validator("visual_style")
    @classmethod
    def _valid_visual_style(cls, v):
        try:
            return math_visual_mod.validate_visual_style(v)
        except math_visual_mod.MathVisualError as e:
            raise ValueError(str(e)) from e

    @field_validator("domain")
    @classmethod
    def _valid_domain(cls, v):
        try:
            return prompts.validate_domain(v)
        except prompts.DomainError as e:
            raise ValueError(str(e)) from e


def _episode_progress(slug):
    paths = manifest_mod.episode_paths(OUTPUT_DIR, slug)
    m = manifest_mod.load_manifest(paths["manifest"])
    if not m:
        return None
    segs = m.get("segments", [])
    complete = [s for s in segs if s.get("status") == "complete"]
    failed = [s for s in segs if s.get("status") == "failed"]
    narration_seconds = sum(s.get("duration") or 0 for s in complete)
    target_duration_seconds = m.get("target_duration_seconds")
    # The outline is deliberately over-provisioned (see pipeline.py's SECONDS_PER_SEGMENT_ESTIMATE
    # buffer and outline-extension logic) and generation stops the instant narration crosses the
    # target -- so a healthy, fully-finished episode routinely ends with one or more outlined
    # segments left "pending", never attempted. segments_complete < segments_total alone doesn't
    # mean "still working, catching up"; this flag disambiguates that from genuine in-progress work.
    target_reached = bool(target_duration_seconds) and narration_seconds >= target_duration_seconds
    final_path = os.path.join(paths["final"], f"{slug}.mp4")
    final_exists = os.path.exists(final_path) and os.path.getsize(final_path) > 0
    final_host_path = (
        os.path.join(HOST_OUTPUT_DIR, os.path.relpath(final_path, OUTPUT_DIR))
        if final_exists and HOST_OUTPUT_DIR else None
    )

    visual_style = m.get("visual_style", math_visual_mod.DEFAULT_VISUAL_STYLE)
    # Narration finishing (target_reached) does not mean the episode is nearly done --
    # per-segment video encoding (and, for visual_style="images", image generation before
    # it) each run once per segment same as narration did, and for a long images-style
    # episode can each take just as long or longer. Surfacing how far each of those later
    # stages has actually gotten (not just "narration: 54/55") is what lets the UI show a
    # real "video 28/54" readout instead of looking stuck once narration hits 100%.
    images_ready = sum(1 for s in complete if s.get("images")) if visual_style == "images" else None
    segment_videos_built = sum(
        1 for s in complete
        if s.get("video") and os.path.exists(os.path.join(paths["root"], s["video"]))
        and os.path.getsize(os.path.join(paths["root"], s["video"])) > 0
    )
    total_complete = len(complete)
    if not target_reached:
        stage = "narrating"
    elif images_ready is not None and images_ready < total_complete:
        stage = "generating_images"
    elif total_complete > 0 and segment_videos_built < total_complete:
        stage = "building_segment_videos"
    elif not final_exists:
        stage = "finalizing"
    else:
        stage = "complete"

    return {
        "slug": slug,
        "title": m.get("title"),
        "topic": m.get("topic"),
        "target_duration_seconds": m.get("target_duration_seconds"),
        "domain": m.get("domain", prompts.DEFAULT_DOMAIN),
        "narration_seconds": narration_seconds,
        "target_reached": target_reached,
        "stage": stage,
        "images_ready": images_ready,
        "segment_videos_built": segment_videos_built,
        "ambient_mood": (m.get("ambient") or {}).get("mood"),
        "pitch_semitones": m.get("pitch_semitones", 0.0),
        "segment_gap_seconds": m.get("segment_gap_seconds", 0.0),
        "sentence_gap_seconds": m.get("sentence_gap_seconds", 0.0),
        "visual_style": visual_style,
        "visual_family": (m.get("visual") or {}).get("family"),
        "music_enabled": (m.get("music") or {}).get("enabled", False),
        "music_track_id": (m.get("music") or {}).get("track_id"),
        "music_file": (m.get("music") or {}).get("file"),
        "segments_total": len(segs),
        "segments_complete": len(complete),
        "segments_failed": len(failed),
        "final_video_exists": final_exists,
        "final_video_path": final_path if final_exists else None,
        "final_video_host_path": final_host_path,
        "youtube_metadata_ready": bool(m.get("youtube")),
    }


def _run_job(job_id, ns):
    job = _jobs[job_id]
    job["status"] = "running"
    job["started_at"] = time.time()
    try:
        result = pipeline.run(ns)
        if result is None:
            job["status"] = "error"
            job["error"] = "pipeline reported failure — see history-api container logs"
            notify.job_failed(job["slug"], job["error"])
        else:
            job["status"] = "complete"
            job["final_path"] = result["final_path"]
            job["narration_seconds"] = result["narration_seconds"]
            job["segment_gap_count"] = result["segment_gap_count"]
            job["video_duration_actual"] = result["video_duration_actual"]
            job["failed_segments"] = [s["number"] for s in result["failed"]]
            notify.job_complete(
                job["slug"],
                result["manifest"].get("title") or job["topic"],
                result["narration_seconds"],
                result["manifest"].get("target_duration_seconds") or job["duration"],
                len(result["failed"]),
            )
    except Exception as e:  # noqa: BLE001 - a job failure must not crash the server
        job["status"] = "error"
        job["error"] = str(e)
        notify.job_failed(job["slug"], job["error"])
    finally:
        job["finished_at"] = time.time()
        with _lock:
            if _active_slugs.get(job["slug"]) == job_id:
                del _active_slugs[job["slug"]]


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/metadata")
def get_metadata():
    """Enum values and numeric bounds for every JobRequest field, straight from the same
    modules Pydantic validates against -- so any client (the Ollama tool's docstrings, a
    future UI) can build a form/schema without hand-copying validation rules that could
    drift out of sync with the API's own.
    """
    return {
        "domains": sorted(prompts.DOMAINS),
        "visual_styles": sorted(math_visual_mod.VALID_VISUAL_STYLES),
        "defaults": {
            "voice": KOKORO_VOICE,
            "speed": KOKORO_SPEED,
            "duration": 3600,
            "ambient": AMBIENT_ENABLED,
            "youtube_metadata": YOUTUBE_METADATA_ENABLED,
            "music": MUSIC_ENABLED,
            "music_mood": MUSIC_MOOD,
            "music_level_db": MUSIC_LEVEL_DB,
            "music_fade_in_seconds": MUSIC_FADE_IN_SECONDS,
            "music_fade_out_seconds": MUSIC_FADE_OUT_SECONDS,
            "segment_gap_seconds": SEGMENT_GAP_SECONDS,
            "sentence_gap_seconds": SENTENCE_GAP_SECONDS,
            "visual_style": VISUAL_STYLE,
            "domain": DOMAIN,
        },
        "bounds": {
            "speed": {"min": 0.25, "max": 4.0},
            "pitch_semitones": {"min": pitch_mod.MIN_SEMITONES, "max": pitch_mod.MAX_SEMITONES},
            "music_level_db": {"min": music_mod.MIN_LEVEL_DB, "max": music_mod.MAX_LEVEL_DB},
            "segment_gap_seconds": {"min": video_mod.MIN_GAP_SECONDS, "max": video_mod.MAX_GAP_SECONDS},
            "sentence_gap_seconds": {
                "min": sentence_gap_mod.MIN_SENTENCE_GAP_SECONDS,
                "max": sentence_gap_mod.MAX_SENTENCE_GAP_SECONDS,
            },
        },
    }


@app.get("/voices/{voice_id}/sample")
def get_voice_sample(voice_id: str):
    """A short (<=10s) preview clip of voice_id, generated once and cached on disk
    thereafter -- see voice_samples.py. Validates voice_id against Kokoro's own live
    voice list first (when reachable) so an arbitrary/garbage id gets a clean 404
    instead of paying for a synthesis call that would just fail anyway.
    """
    try:
        known = kokoro_client.list_voices(KOKORO_URL)
    except Exception:
        known = None  # can't check right now -- fall through and let synthesis itself report the real error
    if known is not None and voice_id not in known:
        raise HTTPException(status_code=404, detail=f"unknown voice id: {voice_id!r}")

    try:
        path = voice_samples.get_or_create(KOKORO_URL, voice_id, VOICE_SAMPLES_DIR)
    except voice_samples.VoiceSampleError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    return FileResponse(path, media_type="audio/mpeg")


@app.post("/jobs", status_code=202)
def create_job(req: JobRequest):
    slug = manifest_mod.slugify(req.topic)

    with _lock:
        existing_job_id = _active_slugs.get(slug)
        if existing_job_id:
            existing = _jobs[existing_job_id]
            return {
                "job_id": existing_job_id,
                "slug": slug,
                "status": "already_running",
                "detail": f"A job for '{slug}' is already {existing['status']}; refusing to start a concurrent run on the same episode.",
            }

        job_id = uuid.uuid4().hex[:12]
        ns = SimpleNamespace(
            topic=req.topic,
            duration=req.duration,
            voice=req.voice,
            speed=req.speed,
            ambient=req.ambient,
            youtube_metadata=req.youtube_metadata,
            pitch_semitones=req.pitch_semitones,
            music=req.music,
            music_mood=req.music_mood,
            music_track_id=req.music_track_id,
            music_level_db=req.music_level_db,
            music_fade_in_seconds=req.music_fade_in_seconds,
            music_fade_out_seconds=req.music_fade_out_seconds,
            music_library_dir=MUSIC_LIBRARY_DIR,
            segment_gap_seconds=req.segment_gap_seconds,
            sentence_gap_seconds=req.sentence_gap_seconds,
            visual_style=req.visual_style,
            domain=req.domain,
            force=req.force,
            model=req.model,
            ollama_url=OLLAMA_URL,
            kokoro_url=KOKORO_URL,
            comfyui_url=COMFYUI_URL,
            output_dir=OUTPUT_DIR,
        )
        _jobs[job_id] = {
            "job_id": job_id,
            "slug": slug,
            "topic": req.topic,
            "duration": req.duration,
            "voice": req.voice,
            "speed": req.speed,
            "ambient": req.ambient,
            "youtube_metadata": req.youtube_metadata,
            "pitch_semitones": req.pitch_semitones,
            "music": req.music,
            "music_mood": req.music_mood,
            "music_track_id": req.music_track_id,
            "segment_gap_seconds": req.segment_gap_seconds,
            "sentence_gap_seconds": req.sentence_gap_seconds,
            "visual_style": req.visual_style,
            "domain": req.domain,
            "status": "queued",
            "error": None,
            "created_at": time.time(),
            "started_at": None,
            "finished_at": None,
        }
        _active_slugs[slug] = job_id
        thread = threading.Thread(target=_run_job, args=(job_id, ns), daemon=True)
        thread.start()

    return {"job_id": job_id, "slug": slug, "status": "started"}


@app.get("/jobs")
def list_jobs():
    """Every job this server process knows about (in-memory, cleared on restart),
    regardless of which client submitted it -- the Configuration UI polls this (not
    per-browser localStorage) so a job started from one browser, the Ollama chat tool,
    or a direct API call is equally visible everywhere. Progress is embedded per job
    (same shape /jobs/{job_id} returns) so the UI can render full status from one call.
    """
    return [{**job, "progress": _episode_progress(job["slug"])} for job in _jobs.values()]


@app.get("/jobs/{job_id}")
def get_job(job_id: str):
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    return {**job, "progress": _episode_progress(job["slug"])}


@app.get("/episodes")
def list_episodes():
    if not os.path.isdir(OUTPUT_DIR):
        return []
    episodes = []
    for slug in sorted(os.listdir(OUTPUT_DIR)):
        progress = _episode_progress(slug)
        if progress:
            episodes.append(progress)
    return episodes


@app.get("/episodes/{slug}")
def get_episode(slug: str):
    progress = _episode_progress(slug)
    if not progress:
        raise HTTPException(status_code=404, detail="episode not found")
    return progress


@app.get("/episodes/{slug}/youtube")
def get_youtube_metadata(slug: str):
    """The cached YouTube upload metadata (title, description, tags, category,
    chapters) generated for this episode -- see youtube_metadata.py. 404 until
    generation has actually run and succeeded (it's best-effort, so a completed episode
    with youtube_metadata disabled, or whose one Ollama call failed, legitimately has
    none yet).
    """
    paths = manifest_mod.episode_paths(OUTPUT_DIR, slug)
    m = manifest_mod.load_manifest(paths["manifest"])
    if not m:
        raise HTTPException(status_code=404, detail="episode not found")
    youtube = m.get("youtube")
    if not youtube:
        raise HTTPException(status_code=404, detail="YouTube metadata not generated yet for this episode")
    return youtube


class GenerateYoutubeRequest(BaseModel):
    force: bool = False


@app.post("/episodes/{slug}/youtube/generate")
def generate_youtube_metadata(slug: str, req: GenerateYoutubeRequest = GenerateYoutubeRequest()):
    """Generate (or, with force, regenerate) this episode's YouTube metadata on demand,
    independent of running the full pipeline -- for an episode that predates this
    feature, had it disabled, or whose one Ollama call failed the first time. Uses the
    same youtube_metadata.generate() the pipeline itself calls (see
    pipeline.py:apply_youtube_metadata), just triggered directly instead of as part of a
    job run, the same way voice_samples.get_or_create() is called directly for the voice
    preview endpoint rather than through a job.
    """
    paths = manifest_mod.episode_paths(OUTPUT_DIR, slug)
    m = manifest_mod.load_manifest(paths["manifest"])
    if not m:
        raise HTTPException(status_code=404, detail="episode not found")

    domain = m.get("domain", prompts.DEFAULT_DOMAIN)
    model = m.get("model") or OLLAMA_MODEL
    result = youtube_metadata.generate(OLLAMA_URL, model, domain, m, paths, force=req.force)
    if not result:
        raise HTTPException(
            status_code=502,
            detail="Generation failed or there are no completed segments yet -- check history-api's logs for the underlying Ollama error.",
        )

    m["youtube"] = result
    manifest_mod.save_manifest(paths["manifest"], m)
    return result


class PublishYoutubeRequest(BaseModel):
    video_id: str


@app.post("/episodes/{slug}/youtube/publish")
def publish_youtube_metadata(slug: str, req: PublishYoutubeRequest):
    """Push this episode's cached YouTube metadata (see get_youtube_metadata above) to
    an already-uploaded video via the YouTube Data API's videos.update -- see
    youtube_publish.py. Requires a one-time OAuth setup (youtube_oauth_setup.py) whose
    output populates YOUTUBE_CLIENT_ID/SECRET/REFRESH_TOKEN; a clear 503 (not a stack
    trace) if that hasn't been done, since it's an operator-side setup gap, not a bad
    request.
    """
    if not (YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET and YOUTUBE_REFRESH_TOKEN):
        raise HTTPException(
            status_code=503,
            detail="YouTube publishing is not configured on this server (missing OAuth credentials)",
        )

    paths = manifest_mod.episode_paths(OUTPUT_DIR, slug)
    m = manifest_mod.load_manifest(paths["manifest"])
    if not m:
        raise HTTPException(status_code=404, detail="episode not found")
    youtube = m.get("youtube")
    if not youtube:
        raise HTTPException(status_code=404, detail="YouTube metadata not generated yet for this episode")

    try:
        youtube_publish.update_video_metadata(
            YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, YOUTUBE_REFRESH_TOKEN, req.video_id, youtube,
        )
    except youtube_publish.YoutubePublishError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e

    youtube["video_id"] = req.video_id
    youtube["published_at"] = time.time()
    m["youtube"] = youtube
    manifest_mod.save_manifest(paths["manifest"], m)

    return {"status": "published", "video_id": req.video_id}
