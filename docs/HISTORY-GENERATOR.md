# History Generator (Batch Video Pipeline)

## Purpose

Generates ~60-minute educational MP4 episodes fully offline, using the existing local AI stack: `qwen3:32b` (via Ollama) writes an outline and per-segment narration scripts, Kokoro synthesizes each segment to speech, `qwen3:32b` also designs a procedural ambient background bed (mood chosen from the topic, no sample library involved), a real human-curated music track can optionally be mixed in from a local library (see [Background Music](#background-music)), and FFmpeg assembles narrated segments plus any background beds into a single video.

It has three ways to trigger a generation run: the `generate.sh` CLI (a one-shot container, run manually), a persistent private API (`history-api`) that Open WebUI can call from a chat via a Tool — see [Open WebUI Integration](#open-webui-integration) — and a small gated browser form — see [Configuration UI](#configuration-ui). `history-api` itself has no gateway route and is never reachable from `edge` or the internet; the Configuration UI is the one deliberate, `basic_auth`-gated exception, since a browser can't reach a Docker-internal-only service directly.

Despite the app/container/service names (`history-generator`, `history-api`, the `historygen_internal` network — kept as-is; nothing about this functionally means "history only"), the content itself isn't history-specific: see [Content Domains](#content-domains). Every other piece of the pipeline — TTS, duration budgeting, pitch, gaps, music, ambient audio, math backgrounds, video assembly, caching — operates on an opaque topic string and has no idea what domain it's serving.

## Content Domains

`domain` (`--domain` CLI, `"domain"` API/chat tool, default **`history`**, one of `history`/`math`/`discovery`) picks which system/segment prompts and outline guidance the LLM gets — the actual "what kind of show is this" knob. Everything else in the pipeline (voice, speed, pitch, gaps, music, ambient, visual backgrounds, video assembly) is domain-agnostic and works identically regardless.

| Domain | What it generates | Notes |
|---|---|---|
| `history` | Past events, people, inventions, places — narrated chronologically | The original/default behavior; prompt text unchanged from before domains existed |
| `math` | Mathematical results, concepts, proofs, patterns, applications | Explicitly told to spell out numbers/formulas in words, never symbolic notation, since this is audio-only. Pairs naturally with `--visual-style math` (see [Math Visualizations](#math-visualizations)), though nothing forces that pairing |
| `discovery` | Present-tense science/how-things-work explainers | Explicitly **not** a history narrative ("how X was discovered") and **not** a news report on recent events — `qwen3:32b` has no internet access and no live data, so this is evergreen ("how black holes form"), not current events. A true current-events domain would need a retrieval/search step feeding it real, dated source material; that doesn't exist yet |

**How it's built**: `src/prompts.py:DOMAINS` is a small registry — each entry holds its own `outline_system`/`segment_system` prompts, a subject-guidance string (what a "segment" should be for that domain), a sequencing hint (chronological vs. logical vs. thematic), its own list of narration requirements, and an `image_style` string used only by `visual_style="images"` (see [AI-Generated Segment Images](#ai-generated-segment-images)). `build_outline_prompt()`/`build_segment_prompt()` take a `domain` argument and look up everything from there; nothing about TTS or audio processing reads `domain` at all. Adding a new domain is adding one entry to that registry — no other file needs to change.

**Chosen once per episode**: like `topic`, `domain` is decided when the episode is first created and reused on every resume — `pipeline.py:resolve_domain()` reads it once from `manifest.json`, and a `--domain` that differs from what's stored is logged and ignored (not applied) rather than silently producing a mixed-style episode. This is different from settings like voice/speed/pitch, which *do* take effect on a resume: those only change how already-written narration is spoken, while domain changes what gets written in the first place, so applying it retroactively would mean regenerating everything anyway. Use `--force` to start an episode over under a different domain. An episode's manifest from before this feature existed has no `"domain"` key at all — it's treated as `history`, which is what its prompts actually asked for, so this is a no-op for every prior episode.

**Tests**: `tests/test_prompts_domains.py` (validation, that the `history` domain's rendered prompt text is byte-identical to before this feature existed, and that `math`/`discovery` produce domain-appropriate wording), `tests/test_pipeline_domain.py` (the once-per-episode resolution/persistence behavior above), and `tests/test_api_domain.py` (API-level validation). Run the same way as the pitch tests (see [Narrator Pitch](#narrator-pitch)).

## Architecture

```text
Topic
  |
  v
qwen3:32b (outline: distinct segment subjects)
  |
  v
qwen3:32b (one segment script at a time)
  |
  v
Kokoro TTS (segment audio)
  |
  v
ffprobe (actual audio duration)
  |
  v
FFmpeg (per-segment video, then concat)  <---  qwen3:32b tool call (mood -> synth params)
  |                                                        |
  |                                                        v
  |                                              FFmpeg (procedural ambient bed)
  v                                                        |
narrated.mp4  ------------------------------------>  FFmpeg (amix under narration)
                                                             |
                                                             v
                                                       ~60-minute MP4
```

Two services share the same image and the same pipeline code (`src/pipeline.py`), and both write into the same bind-mounted `output/` directory:

- **`history-generator`** — the original one-shot CLI container (`docker compose run`, not `up`), used by `generate.sh`.
- **`history-api`** — a persistent (`restart: unless-stopped`) FastAPI service wrapping the same pipeline for programmatic/background triggering (see below). Runs `pipeline.run()` in a background thread per job instead of exiting after one run.

Both join the existing private `ollama_internal` and `tts_internal` networks — the same two Open WebUI already bridges — and talk to `http://ollama:11434` and `http://kokoro:8880` exactly as Open WebUI does. Both also join `comfyui_internal`, a private network shared only with the standalone `comfyui` service (`/srv/apps/comfyui`), reached at `http://comfyui:8188` — used only when `visual_style="images"`, see [AI-Generated Segment Images](#ai-generated-segment-images). `history-api` additionally joins a fourth private network, `historygen_internal`, shared with Open WebUI and `history-ui`, so both can reach it at `http://history-api:8000`. None of these services join `edge`; `history-api` and `comfyui` publish no host port.

A third, separate service and image, **`history-ui`** (own `Dockerfile`, `ui/`), is the one piece of this app meant to be reached from a browser — a thin proxy with no pipeline code of its own. See [Configuration UI](#configuration-ui) for its full request path.

## Files

```text
/srv/apps/history-generator/
    compose.yaml
    Dockerfile
    generate.sh
    youtube_oauth_setup.py   # one-time interactive OAuth consent flow, see YouTube Metadata -> Publishing
    .env            # NTFY_TOKEN, YOUTUBE_CLIENT_ID/SECRET/REFRESH_TOKEN — chmod 600, not committed anywhere
    src/            application code (Python): main.py (CLI), api.py (HTTP API), pipeline.py,
                     prompts.py (per-domain outline/segment prompts, see Content Domains),
                     ambient.py (procedural ambient audio design/render), pitch.py (narrator
                     pitch shifting), sentence_gap.py (within-segment pauses), music.py
                     (background-music selection/preparation), music_catalog.py (catalog
                     scan/load/save), scan_music.py (CLI scanner entrypoint), math_visual.py
                     (animated mathematical backgrounds, also owns the shared visual_style
                     enum), segment_images.py (per-segment AI image generation/caching, see
                     AI-Generated Segment Images), image_client.py (ComfyUI HTTP client),
                     youtube_metadata.py (title/description/tags/category/chapters from
                     the finished script, see YouTube Metadata), youtube_publish.py
                     (pushes that metadata to a real uploaded video via the YouTube Data
                     API v3, see Publishing metadata to a real YouTube video),
                     gpu_lock.py (process-wide mutex serializing Ollama/ComfyUI GPU calls),
                     voice_samples.py (cached <=10s voice-preview clips, see Configuration
                     UI -> Voice Preview), kokoro_client.py (Kokoro HTTP client, incl.
                     list_voices()), ollama_client.py (Ollama HTTP client),
                     notify.py (push notifications), ...
    tests/          pytest suite (not baked into the image)
    requirements-dev.txt   # pytest, for running tests/ — not installed in the container image
    output/         generated episodes (bind mount, host-owned)
    voice_samples/  cached voice-preview clips (bind mount -- see Configuration UI -> Voice Preview)
    ui/             the Configuration UI service (own image, own compose service) -- see below
        Dockerfile
        requirements.txt
        main.py       # thin proxy to history-api (and, for /api/voices, kokoro) -- no pipeline code
        static/       # index.html, app.js, style.css -- plain HTML/CSS/vanilla JS, no build step
        tests/
        requirements-dev.txt
    sync-jellyfin-library.sh   # hardlinks finished episodes into /srv/media -- see Jellyfin Preview below
    sync-jellyfin-library.log  # its cron run history (crontab -l shows the schedule)

/srv/apps/open-webui/
    compose.yaml
    tools/
        history_generator_tool.py   # reference copy; installed via the Open WebUI UI, not a bind mount

/srv/apps/gateway/
    Caddyfile       # generator.example.com's basic_auth route lives here -- see Configuration UI below

/srv/apps/ntfy/
    compose.yaml    # private push-notification server — see Open WebUI Integration below

/srv/media/audio/
    music/          # background-music library — see Background Music below
        catalog.json      # scanned/human-reviewed track metadata (created by scan_music.py)
        sleep-ambient/    # a category folder; tracks are just discovered wherever they sit
    effects/        # a separate sound-effects library, unrelated to this pipeline

/srv/media/
    generated-episodes/   # hardlinks to finished episodes, for Jellyfin -- see Jellyfin Preview below
```

The container runs as `1000:1000` (matching the `appuser` host user) specifically so files written under `output/` are owned by the normal user, not root.

Each episode gets its own directory under `output/<episode-slug>/`:

```text
output/<episode-slug>/
    manifest.json       # source of truth: outline, per-segment status/duration, chosen ambient/music params,
                          # and (under "youtube") generated YouTube upload metadata -- see YouTube Metadata
    scripts/NNN.txt      # narration text per segment
    audio/NNN.mp3         # synthesized narration per segment -- one Kokoro call, or several joined
                            # with sentence_gap_seconds of silence if that's > 0 (see Sentence Gaps);
                            # re-synthesized only when voice/speed/sentence_gap_seconds changes
    audio/NNN.pitch.mp3    # pitch-shifted narration (only present when pitch_semitones != 0)
    video/NNN.mp4          # per-segment video (background + title text + narration, pitched if applicable)
    video/.ambient.wav      # rendered ambient bed (only when ambient is enabled)
    video/.music.wav         # prepared background music, looped/trimmed/leveled (only when music is enabled)
    video/.gap.mp4           # silent blank clip inserted between segments (only when segment_gap_seconds > 0), rebuilt every run
    video/.math_bg.mp4       # rendered math-visualization loop (only when visual_style="math"), cached like the ambient bed
    images/NNN_II.png        # AI-generated segment stills (only when visual_style="images"), see AI-Generated Segment Images
    video/.narrated.mp4      # concatenated video before ambient/music are mixed in (only when either is enabled)
    final/<slug>.mp4        # concatenated final episode
```

## How to Generate an Episode

```bash
cd /srv/apps/history-generator
```

**1. Run a short test first.** Always validate the pipeline with a 5-minute episode before committing to a full hour — it exercises every stage (outline → script → TTS → duration measurement → video → concat) in about a minute:

```bash
./generate.sh --duration 300 "Ancient Rome"
```

`generate.sh` builds the image first (a no-op if `src/` hasn't changed since the last build) and then runs the container.

**2. Watch the progress log.** Each segment prints its script/narration steps and a running total:

```text
Episode: Ancient Rome
Target: 300 seconds

[01] The Founding of Rome: Legends and Reality
     Generating script...
     Generating narration...
     Duration: 84.3 sec
     Total: 84.3 / 300
```

**3. Find the output.** When it finishes, the final report gives the exact path:

```text
Final MP4: /app/output/ancient-rome/final/ancient-rome.mp4
```

That `/app/output/...` path is inside the container; on the host it's the same path under the project directory:

```bash
ls /srv/apps/history-generator/output/ancient-rome/final/
```

**4. Play it.** The file is a standard MP4 (H.264/AAC), owned by your normal user — open it directly with VLC, `mpv`, a browser, or copy it off the server:

```bash
scp rtx:/srv/apps/history-generator/output/ancient-rome/final/ancient-rome.mp4 .
```

**5. Generate the real ~60-minute episode**, once the test looks/sounds right:

```bash
./generate.sh "Ancient Rome"
```

This resumes the same `ancient-rome` episode (test-run segments 1-4 are kept, generation continues from segment 5) rather than starting over — see [Resumability](#resumability). If you'd rather start that topic completely fresh instead of continuing the test episode, add `--force`.

**Other options:**

```bash
# force full regeneration instead of resuming
./generate.sh --force "Ancient Rome"

# different voice
./generate.sh --voice af_bella "The American Revolution"

# slower narration (0.8 = 20% slower, 1.0 = normal, 1.25 = 25% faster)
./generate.sh --speed 0.8 "The American Revolution"

# no ambient background bed, narration only
./generate.sh --no-ambient "Ancient Rome"

# deeper, more dramatic-sounding narrator (speaking speed unaffected)
./generate.sh --pitch -2 "The Fall of Constantinople"

# add real background music, auto-picked from the "sleep-ambient" catalog category
./generate.sh --music "Glaciers in Massachusetts"

# background music from an exact, known catalog track
./generate.sh --music --music-track-id 8deebe159302 "Glaciers in Massachusetts"
```

Flags: `--duration <seconds>` (default 3600), `--voice <kokoro-voice>` (default `af_heart`), `--speed <float>` (default 1.0; Kokoro accepts roughly 0.25-4.0), `--ambient` / `--no-ambient` (default on; see [Ambient Audio](#ambient-audio)), `--pitch <semitones>` (default 0.0, range -4.0 to +4.0; see [Narrator Pitch](#narrator-pitch)), `--music` / `--no-music` (default off; see [Background Music](#background-music)), `--music-mood`, `--music-track-id`, `--music-level`, `--music-fade-in`, `--music-fade-out`, `--music-library-dir`, `--segment-gap <seconds>` (default 1.5, range 0-10; see [Segment Gaps](#segment-gaps)), `--sentence-gap <seconds>` (default 0.5, range 0-2; see [Sentence Gaps](#sentence-gaps)), `--visual-style {static,math,images}` (default `static`; see [Math Visualizations](#math-visualizations) and [AI-Generated Segment Images](#ai-generated-segment-images)), `--domain {history,math,discovery}` (default `history`; see [Content Domains](#content-domains)), `--force` (wipe and regenerate instead of resuming), `--model`, `--ollama-url`, `--kokoro-url`, `--comfyui-url` (default `http://comfyui:8188`; only used by `visual_style="images"`), `--output-dir` (all default to the existing stack, rarely need overriding).

Changing `--voice` or `--speed` when resuming an episode automatically invalidates every already-generated segment's narration and video (Kokoro bakes both directly into the synthesized audio, so there's no way to patch them in place) — the next run re-synthesizes all of them at the new setting. Scripts are untouched, so nothing gets reworded, and you don't need `--force` (which wipes the whole episode, including the outline) just to switch voice or speed. See [Resumability](#resumability).

A full ~60-minute run takes roughly 45 outline-estimated segments; at the pace seen in testing (~15-20s per segment for script + narration), expect on the order of 15-20 minutes of generation time, plus final video assembly. It's safe to leave running unattended and safe to interrupt — see below.

## Open WebUI Integration

Episodes can also be triggered from an Open WebUI chat instead of the CLI, backed by the `history-api` service described above. This is useful for kicking off a generation run without SSHing in, and for checking on one later.

### How it works

```text
You (in Open WebUI chat)
  |
  v
qwen3:32b decides to call a Tool function
  |
  v
Tool -> POST/GET http://history-api:8000/... (historygen_internal network)
  |
  v
history-api starts a background thread running the SAME pipeline.run()
the CLI uses, writing into the same output/ directory and manifest.json
  |
  v
Tool result -> chat reply
```

The Tool call itself returns almost instantly — it only starts the job or reads `manifest.json`-derived progress; it never waits for a full episode to finish generating. `qwen3:32b` continues serving normal chat while `history-api`'s background thread does the actual work (which itself calls `qwen3:32b` again for scripts, so a couple of requests will interleave on the model — this is the same Ollama instance and model used everywhere else, nothing extra is deployed).

### One-time setup: install the Tool

1. Open **https://ai.example.com**, sign in as an admin.
2. Go to **Workspace → Tools → +** (create new tool).
3. Paste in the contents of `/srv/apps/open-webui/tools/history_generator_tool.py`.
4. Save. Give it an id/name if prompted (e.g. `history_generator`).
5. Enable the tool for whichever model(s) you want to be able to trigger episodes — e.g. edit the model (or a "History Tutor" preset built on `qwen3:32b`) and turn the tool on for it, or enable it globally.

Open WebUI's own docs are explicit that Workspace Tools run arbitrary Python **inside** the Open WebUI backend — review the file before pasting it in, and only admins should have Workspace access (this server's `ENABLE_SIGNUP=false` setup already limits who can sign in at all).

The Tool talks to `http://history-api:8000` by default (its `Valves.api_base_url`, editable from the tool's settings in the UI if that ever needs to change — it shouldn't, since it's an internal Docker DNS name).

The copy pasted into Workspace → Tools is a **snapshot**, not synced with this repo — if `history_generator_tool.py` changes here (new parameters, bug fixes), the installed Tool stays on the old version until you re-paste it. Check the `version:` line in the file's header comment against what you last installed if a chat request doesn't seem to know about a feature that's documented here (e.g. `ambient`). This isn't hypothetical: the installed copy was found stuck on `0.1.0` (missing `pitch_semitones`, `music`, `segment_gap_seconds`, `sentence_gap_seconds` entirely) well after all of those had been added here.

**Updating the installed Tool after `history_generator_tool.py` changes** — two options:

1. **UI re-paste** (simplest, no server access needed): Workspace → Tools → History Generator → Edit → replace the contents with the current file → Save. Open WebUI regenerates the tool-calling schema (its `specs`, what tells the model which parameters exist) from the docstring automatically on save.
2. **Scripted update** (useful when re-pasting by hand is impractical, e.g. from an agent/automation): Open WebUI stores each tool's `content` and `specs` in its own SQLite DB (`open_webui_data` volume, `webui.db`, `tool` table) — editing `content` alone is not enough, since a stale `specs` still won't tell the model about new parameters. Regenerate both together using Open WebUI's own loader, from inside the `open-webui` container:
   ```python
   # inside the open-webui container, e.g. via `docker exec`
   import asyncio, sys
   sys.path.insert(0, "/app/backend")
   from open_webui.utils.plugin import load_tool_module_by_id
   from open_webui.utils.tools import get_tool_specs
   from open_webui.models.tools import Tools

   async def main():
       content = open("/path/to/history_generator_tool.py").read()
       tools_obj, _ = await load_tool_module_by_id("history_generator", content=content)
       specs = get_tool_specs(tools_obj)
       await Tools.update_tool_by_id("history_generator", {"content": content, "specs": specs})

   asyncio.run(main())
   ```
   This needs `WEBUI_SECRET_KEY` set in the environment (the running container's actual key is at `/app/backend/.webui_secret_key`, since `open_webui.env` raises on import otherwise). No restart is required either way — `get_tool_module_from_cache()` re-fetches `content` from the DB on every tool invocation and reloads the module whenever it differs from what's cached, so an updated tool takes effect on the very next chat message. **Always back up `webui.db` first** (`cp webui.db webui.db.bak-$(date +%Y%m%d-%H%M%S)` in the container) before writing to it directly.

**Enabling the Tool by default for a model**: Workspace → Models → (your model) → Tools → toggle History Generator on → Save. This sets `toolIds` in the model's stored `meta` (Open WebUI's `model` table) — without it, the Tool still works but has to be toggled on per-chat via the "+" tools icon next to the message box. The same `Tools`-style pattern (fetch the model, add `"history_generator"` to `meta.toolIds`, call `Models.update_model_by_id`) can be scripted the same way as above if needed, preserving every other field on the model untouched.

### Using it in chat

Once enabled for a model, just ask in normal language, e.g.:

```text
Generate a 5 minute test episode about the Great Fire of London.
```

```text
What's the status of the ancient-rome episode?
```

```text
List all the history episodes.
```

```text
Make a calm 10 minute episode about glaciers, with a deeper narrator voice and some sleep-ambient background music.
```

The model picks the right function (`start_history_episode`, `check_history_episode_status`, `list_history_episodes`) based on the docstrings in the Tool file — it isn't hardcoded to specific phrasing.

### Getting the finished video

`history-api` is intentionally not on the `edge` network (see [Security Requirements] in `AGENTS.md` — it's never been made publicly reachable), so there's no browser URL for a finished episode. `check_history_episode_status` instead reports the real **host filesystem path** — `HOST_OUTPUT_DIR` (set in `compose.yaml`, e.g. `/srv/apps/history-generator/output`) plus the episode's path relative to the container's `OUTPUT_DIR` — since `./output` is just a bind mount, that host path is directly openable on the server (or over `scp`/a file share) once the job completes. `GET /episodes/{slug}` exposes this as `final_video_host_path` (falls back to `null` if `HOST_OUTPUT_DIR` is unset, in which case only the container-internal `final_video_path` is available). If browser access to finished videos is wanted later, treat it as a deliberate exposure decision (a small authenticated download endpoint + a gated Caddy route, or proxying the bytes through Open WebUI's own already-authenticated file storage) rather than adding `history-api` to `edge` — see `src/api.py:_episode_progress()`.

### Push notifications (no polling required)

You don't have to ask the chat to check status — `history-api` pushes a real notification to your phone/desktop the moment a job finishes (success or failure), via a private self-hosted [ntfy](https://ntfy.sh) instance. Start a job, close the chat entirely, and you'll still get pinged.

```text
history-api background thread
  |
  v
pipeline.run() returns (success or failure)
  |
  v
notify.job_complete() / notify.job_failed()   [src/notify.py — best-effort, never
  |                                             raises; a notification failure
  v                                             can't take down a job]
POST https://ntfy.example.com/history-generator
  (Bearer token auth)
  |
  v
ntfy app on your phone/desktop
```

**Architecture:**

- `/srv/apps/ntfy` — a private ntfy server (`binwiederhier/ntfy`), auth mode `deny-all` by default (nobody gets read/write access unless explicitly granted). Public at `https://ntfy.example.com` (through Caddy, same pattern as every other public hostname on this server) so the phone/desktop app can reach it from anywhere, but **anonymous publish/read is refused** — confirmed via a 403 during setup.
- User `roberto` has exclusive read-write access to the one topic used here, `history-generator`.
- `history-api` publishes using a **scoped access token** for that user/topic (`NTFY_TOKEN` in `/srv/apps/history-generator/.env`, chmod 600, not committed anywhere) — not the account password.
- `ntfy` joins `historygen_internal` (so `history-api` reaches it at `http://ntfy:80` over the private network, not round-tripping through the public internet for a same-server call) in addition to `edge` (for the public app).

**One-time setup to actually receive them:**

1. Install the ntfy app ([Android](https://play.google.com/store/apps/details?id=io.heckel.ntfy) / [iOS](https://apps.apple.com/us/app/ntfy/id1625396347) / or just use a browser at the URL below).
2. Add server: `https://ntfy.example.com`, log in as `roberto` (ask for the password if you don't have it — it's not written down here).
3. Subscribe to topic `history-generator`.

**Config (`/srv/apps/history-generator/compose.yaml`, `history-api` service):**

```yaml
environment:
  - NTFY_URL=http://ntfy:80
  - NTFY_TOPIC=history-generator
  - NTFY_TOKEN=${NTFY_TOKEN}   # from .env, not hardcoded
```

If `NTFY_URL`/`NTFY_TOPIC`/`NTFY_TOKEN` aren't all set, `notify.py` silently no-ops — jobs still run and complete normally, you just won't get pushed a notification. This is deliberate: notifications are a convenience layer on top of the pipeline, not a dependency of it.

**Managing the ntfy user/token:**

```bash
# add another user (e.g. a second person who wants their own notifications)
docker exec ntfy ntfy user add someoneelse
docker exec ntfy ntfy access someoneelse history-generator rw

# rotate history-api's token (then update .env and recreate history-api)
docker exec ntfy ntfy token add --label="history-api" roberto
docker exec ntfy ntfy token list roberto

# see who has access to what
docker exec ntfy ntfy user list
```

### The API directly

For scripting or debugging without going through chat, `history-api` is reachable from any container on `historygen_internal` or `ollama_internal`/`tts_internal` (e.g. from `open-webui` or `history-generator` itself), but not from the host directly (no published port):

```bash
# start a job
docker exec open-webui curl -s -X POST http://history-api:8000/jobs \
  -H "Content-Type: application/json" \
  -d '{"topic": "Ancient Rome", "duration": 300, "voice": "af_heart", "speed": 0.8, "ambient": true, "pitch_semitones": -2, "music": true, "music_mood": "sleep-ambient"}'
# -> {"job_id": "...", "slug": "ancient-rome", "status": "started"}

# check a specific job (includes live manifest-derived progress)
docker exec open-webui curl -s http://history-api:8000/jobs/<job_id>

# check by episode slug instead (works even after history-api restarts,
# since it reads manifest.json rather than in-memory job state)
docker exec open-webui curl -s http://history-api:8000/episodes/ancient-rome

# list every episode found under output/
docker exec open-webui curl -s http://history-api:8000/episodes

docker exec open-webui curl -s http://history-api:8000/health
```

Posting a `topic` that's already actively running (same slug) does **not** start a second concurrent run — the API returns `"status": "already_running"` and leaves the existing job alone, since two runs against the same `manifest.json` at once would corrupt it.

`history-api`'s in-memory job list (`GET /jobs`) is lost if the container restarts, but episode progress (`GET /episodes`, `GET /episodes/<slug>`) always reflects `manifest.json` on disk, so it survives restarts.

### Logs

`history-api` prints the same progress output the CLI prints (per-segment script/narration/duration lines), just to its own container logs instead of your terminal:

```bash
docker logs -f history-api
```

## Configuration UI

A small browser-based form for starting and tracking jobs without going through a chat prompt at all — **`https://generator.example.com`**, gated by Caddy `basic_auth` (same pattern as `docs.example.com`). This is additive: the Open WebUI Tool above still works exactly as before, and both submit to the exact same `history-api` job queue, so a job started from either place shows up identically in the other (and in `GET /episodes`).

### Why a separate service, and why this hostname

Open WebUI (v0.11.3, as installed here) has no supported extension point for a persistent, non-chat settings page — Tools/Functions/Artifacts are all chat-embedded, which doesn't fit "configure and submit a job without an LLM in the loop." So this is a small standalone app instead, per the documented fallback for that case.

`history-api` stays exactly as private as before — it never joins `edge` and has no gateway route. A new service, **`history-ui`** (`/srv/apps/history-generator/ui/`), sits in front of it:

```text
Browser (generator.example.com)
  |
Caddy (basic_auth)
  |
edge
  |
history-ui  --- historygen_internal ---  history-api  (job queue, all validation,
  |                                          |          voice-sample synthesis/cache)
  |                                          +-- tts_internal --- kokoro (synthesis)
  +-- tts_internal --- kokoro (voice *list* only, GET /v1/audio/voices)
```

`history-ui` is a thin proxy with **zero generation logic and zero validation rules of its own** — every `/api/*` route just forwards to the matching `history-api` route (`POST /jobs`, `GET /jobs`, `GET /jobs/{id}`, `GET /episodes`, `GET /episodes/{slug}`) and returns the response verbatim, including validation error bodies. The one exception is `GET /api/voices`, which queries Kokoro directly (`GET /v1/audio/voices`) for a real, live voice list rather than hand-maintaining a copy of it that could drift stale. Static assets (`ui/static/index.html`, `app.js`, `style.css` — plain HTML/CSS/vanilla JS, no build step, no framework) are served at `/`.

The Ollama-facing side (`ollama_internal`) is deliberately **not** reachable from `history-ui` — it has no reason to talk to Ollama or synthesize anything itself.

### Single source of truth for validation

The form's dropdowns, ranges, and bounds all come from a new `GET /metadata` endpoint on `history-api` itself (`src/api.py:get_metadata()`), which reads the same constants every `JobRequest` field is validated against (`prompts.DOMAINS`, `math_visual.VALID_VISUAL_STYLES`, `pitch.MIN/MAX_SEMITONES`, `video.MIN/MAX_GAP_SECONDS`, `sentence_gap.MIN/MAX_SENTENCE_GAP_SECONDS`, `music.MIN/MAX_LEVEL_DB`) — so the UI can never drift out of sync with what the API will actually accept. Client-side validation is a courtesy (instant feedback, no round-trip); the API's own Pydantic validation is still the real gate, and its error messages are surfaced verbatim if something slips through.

### Presets

One built-in preset, **Relaxed Documentary** (`bm_atten_inno`, speed 0.85, sentence gap 0.5s, segment gap 1.5s, music on at `sleep-ambient`/-12dBFS, ambient off), loaded by default on first visit. "Save current as preset" stores the current form state — under a name you choose — in the browser's `localStorage`; "Delete selected preset" removes a saved (non-built-in) one. Presets store only generation settings, never credentials, and never leave the browser (no server-side preset storage exists). Loading a preset fills the form but doesn't submit it — every field stays editable before you hit "Start generation."

### Voice Preview

A "&#9658; Preview voice" button next to the voice picker plays a short (&le;10s) sample so you can hear a voice before committing an episode to it, using a fixed sample sentence ("The quiet hum of history drifts through time...") synthesized in that voice.

**Lives on `history-api`, not `history-ui`**: generating audio is generation logic, so — unlike everything else in this section — it belongs with the rest of the pipeline's TTS code, not in the UI's thin proxy. `src/voice_samples.py:get_or_create()` calls the same `kokoro_client.synthesize()` used for real narration, then runs the result through a plain `ffmpeg -t 10` trim (voices don't all pace the same sample text identically, so this is what actually guarantees the cap, not just asking for a short sentence and hoping). Cached to disk at `VOICE_SAMPLES_DIR` (`/app/voice_samples`, bind-mounted to `./voice_samples` — persists across rebuilds, not baked into the image) keyed by voice id, so a given voice is only ever synthesized once. `GET /voices/{voice_id}/sample` on `history-api` serves the cached file (generating it first on a cache miss), 404s for a voice id Kokoro doesn't actually have (checked live against `kokoro_client.list_voices()`, never a hand-maintained list), and 502s if synthesis itself fails. `history-ui` adds one thin passthrough route, `GET /api/voices/{voice_id}/sample` — the one place its normal JSON-wrapping proxy helper doesn't apply, since wrapping mp3 bytes as JSON would corrupt them.

**Pre-warmed at startup**, not generated lazily on first click: `history-api`'s startup (via FastAPI's `lifespan`, not the deprecated `on_event`) kicks off a background thread that walks every voice Kokoro currently reports and synthesizes+caches each one, sequentially — deliberately not in parallel, since Kokoro runs on CPU (see [GPU / VRAM](#gpu--vram)) and a burst of concurrent synthesis calls at startup is exactly the kind of thing that could contend with an actual generation job starting around the same time. Best-effort throughout: an unreachable Kokoro at startup, or a single voice failing, is logged (`docker logs history-api`, look for `voice-sample pre-warm`) and never crashes the API or blocks the rest of the pre-warm. With Kokoro's current 72 voices, this takes a couple of minutes total, once, the first time each voice is ever needed — after that it's pure cache hits, so the button is instant regardless of who clicks it first.

### Initial page load

`init()` in `app.js` used to `await` metadata and voices sequentially before starting *anything* else -- including the jobs and episodes lists, which don't depend on either. `loadVoices()` hits Kokoro directly (`GET /api/voices` -> `KOKORO_URL/v1/audio/voices`), and Kokoro can be slow to respond while it's mid-synthesis for an active job, which meant a slow Kokoro response silently stalled the entire page rather than just the voice dropdown. Jobs/episodes now load immediately and in parallel with metadata/voices instead of behind them, and a thin animated bar under the header (`#init-loading-bar`, shown/hidden around `Promise.all([loadMetadata(), loadVoices()])`) covers the part of the page that's genuinely still waiting -- the domain/visual-style/voice dropdowns and the preset that picks values from them.

### Tracking jobs and finding the output

The "Active & recent jobs" panel is driven entirely by `GET /api/jobs` (polled every ~8s), which now embeds each job's progress — segments complete, narration vs. target duration, domain, and (once done) the same `final_video_host_path` the Open WebUI tool reports (see [Getting the finished video](#getting-the-finished-video)): a real path on the server's filesystem, not a browser download link. Server truth, not `localStorage`, is the source of what's shown: `history-api`'s in-memory job registry already remembers every job it's run since its last restart regardless of who started it, so a job begun from Open WebUI, a different browser, or a direct API call is equally visible here, live, without a page reload. `localStorage` is used only for a per-browser "dismissed" set (hiding a finished/errored job you've already seen) — dismissing a job never affects what the server remembers or what shows up in another browser. This replaced an earlier version that tracked jobs by `job_id` in `localStorage`, which went stale the moment a job failed and was resubmitted under a new `job_id`, or was invisible to any browser besides the one that submitted it. An "All episodes on this server" panel (`GET /api/episodes`, refreshed on the same interval) lists every episode independent of job state at all, useful once a job has aged out of `history-api`'s in-memory registry (i.e. after a restart) but its manifest is still on disk.

**Reading progress past 100% narration**: the outline is deliberately over-provisioned (`pipeline.py`'s `+2`-segment buffer, and its outline-extension logic), and generation stops the instant narration crosses the target duration -- so a finished episode routinely ends with `segments_complete` a little short of `segments_total` (a 60-minute `cosmos-and-beyond` test episode finished at 54/55, having outlined one segment as buffer it never needed). That is not a stuck job. `_episode_progress()` exposes `target_reached` (narration has met the target) for exactly this, and both panels use it: once true, they stop showing the raw `complete/total` fraction and switch to `"N segments narrated (target reached)"`.

Narration finishing isn't the same as the episode being done, either -- for a long `visual_style="images"` episode especially, image generation and then per-segment video encoding each run once per segment just like narration did, and can each take just as long. `_episode_progress()` tracks each stage explicitly via a computed `stage` field (`narrating` → `generating_images` (only when `visual_style="images"`) → `building_segment_videos` → `finalizing` → `complete`), plus raw counts (`images_ready`, `segment_videos_built`) so the UI can show real progress through whichever stage is active -- e.g. `"Building segment videos: 28/54"` -- instead of the display looking frozen once narration hits 100%.

### Deploying a UI change

`history-ui` is its own Docker Compose service inside the same `compose.yaml` as `history-generator`/`history-api`, building from `./ui`:

```bash
cd /srv/apps/history-generator
docker compose build history-ui
docker compose up -d history-ui
```

No Caddy change is needed for a UI-only code change (`main.py`, `static/*`) — only for routing/hostname/auth changes, which additionally need `docker compose -f /srv/apps/gateway/compose.yaml up -d --force-recreate` (not just `restart` or `caddy reload`, both of which were found to keep serving a stale bind-mounted `Caddyfile` after an in-place file replacement — the container has to actually be recreated to re-resolve the mount).

### Tests

`ui/tests/test_main.py` (proxy forwarding to the right upstream path for every route, verbatim passthrough of validation-error bodies, graceful `502` instead of a crash when `history-api` is unreachable, voice-list simplification/sorting and graceful degradation to an empty list when Kokoro is unreachable, and the voice-sample route's binary passthrough/404/502 behavior), `tests/test_api_metadata.py` in the main project (that `/metadata`'s values genuinely come from the same modules Pydantic validates against, not a hand-copied duplicate), and `tests/test_voice_samples.py` + `tests/test_api_voice_samples.py` (synthesis-and-trim behavior, per-voice caching, unsafe-voice-id rejection, the 404/502 endpoint behavior, and that the startup pre-warm keeps going after one voice fails and never raises when Kokoro is unreachable). Run the UI's suite the same way as the main project's (see [Narrator Pitch](#narrator-pitch)), but from `ui/`:

```bash
cd /srv/apps/history-generator/ui
docker build -t history-generator-ui:local .
docker run --rm -v "$PWD/tests:/app/tests:ro" --entrypoint sh history-generator-ui:local \
  -c "pip install --quiet pytest && cd /app && python3 -m pytest tests -v"
```

## Jellyfin Preview

Finished episodes can be browsed/played from the existing Jellyfin server (`/srv/apps/jellyfin`) rather than only via `final_video_host_path`. This needed no Docker/compose changes at all: `output/` (`/srv/apps/history-generator/output`) and Jellyfin's existing `/srv/media` mount live on the **same host filesystem**, so finished episodes are exposed with plain hardlinks — zero extra disk space, since a hardlink is just another directory entry pointing at the same data, not a copy.

**How it works**: `sync-jellyfin-library.sh` walks `output/*/final/*.mp4` and, for each one whose filename stem exactly matches its episode slug (`output/<slug>/final/<slug>.mp4`), hardlinks it into `/srv/media/generated-episodes/<slug>.mp4` — a new folder inside the directory tree Jellyfin already has mounted read-only at `/media`. Matching "filename stem == slug" is what keeps this clean without any special-casing:

- A `--force`-regenerated episode's stale pre-regeneration copy (`<slug>.pre-*-backup-.../final/<slug>.mp4`, made by hand during earlier testing) fails the match on the *directory* name, not the file, so it's skipped.
- A comparison-render file (e.g. `<slug>/final/<slug>.sentence-gap-0.mp4`, also from earlier testing) fails the match on the *file* name, so it's skipped too.

Only the one canonical final video per episode ever gets linked.

**Content changes are detected, not just new files**: re-running the script is always safe, but it's not just "link if missing" — regenerating an episode (`--force`) writes a brand-new `final.mp4` at the same path with a **different inode**, while the old hardlink over in `/srv/media/generated-episodes/` is an independent directory entry that would otherwise go on pointing at the old inode's (now orphaned, but still fully intact) data forever, silently showing Jellyfin stale content. The script compares `stat`'s device:inode pair (not mtime/size, which a coincidental rewrite could match) between the source and the existing link, and re-links (`ln -f`) whenever they differ.

**Automatic**: a host crontab entry runs it every 15 minutes:

```text
*/15 * * * * /srv/apps/history-generator/sync-jellyfin-library.sh >> /srv/apps/history-generator/sync-jellyfin-library.log 2>&1
```

Check `crontab -l` to see it, and `sync-jellyfin-library.log` for its run history. It's also always safe to run by hand for an immediate sync instead of waiting up to 15 minutes:

```bash
/srv/apps/history-generator/sync-jellyfin-library.sh
```

**One-time Jellyfin-side setup** (can't be scripted from here — needs your Jellyfin admin login): Dashboard → Libraries → Add Media Library → content type "Movies" (or "Home Videos") → folder `/media/generated-episodes` → Save.

**Known limitation**: if an episode is deleted entirely from `output/` (not just regenerated), its hardlink in `/srv/media/generated-episodes/` is *not* automatically removed — the script only adds/updates links for episodes that currently exist, it never deletes. Clean up manually (`rm /srv/media/generated-episodes/<slug>.mp4`) if that ever matters.

## YouTube Metadata

`youtube_metadata` (`--youtube-metadata`/`--no-youtube-metadata` CLI, `"youtube_metadata"` API/chat tool, default **on**) generates YouTube upload metadata -- title, description, tags, category, and chapter timestamps -- from an episode's own finished script, once narration completes. It runs automatically; there's no separate command to trigger it.

**Two very different sources feed the result**:

- **Chapters** are pure arithmetic, not an LLM call: `youtube_metadata.py:compute_chapters()` walks the complete segments in order, accumulating each one's actual `duration` plus `segment_gap_seconds`, and formats a `"<timestamp> <title>"` line per segment (`M:SS` under an hour, `H:MM:SS` at or past it). This is exactly the timeline `video.py`'s own assembly follows (see [Video](#video)), so a chapter timestamp always lands on that segment's real start time in the finished file -- never approximate, never re-derived from a duration estimate.
- **Title, description, tags, and category** come from a single Ollama tool call (`propose_youtube_metadata`, see `prompts.py:build_youtube_metadata_system/tool/user`) over the *entire* concatenated script, in order -- one call per episode, not per segment, since (unlike image prompts) there's no natural per-item split to divide a shared budget across. The system prompt is domain-aware (reuses each domain's `label`, see [Content Domains](#content-domains)) and explicitly told not to invent facts beyond the script or include timestamps in the description (chapters are appended separately, verbatim).

**Caching/invalidation**: `pipeline.py:apply_youtube_metadata()` stores the result in `manifest.json` under `"youtube"`, keyed on `generated_for_segment_count` -- the number of complete segments at generation time. A resume that doesn't add segments reuses it untouched (no re-ask); one that does (e.g. after an outline extension) is treated as the content having grown enough to regenerate. `--force` always regenerates. Because scripts are immutable once written (see [Resumability](#resumability)) and this only reads from them, there's no other invalidation trigger to track.

**Best-effort**: a failed Ollama call is logged (`[warn] YouTube metadata generation failed, skipping: ...`) and `generate()` returns `None` -- the episode's video still gets built normally either way. This also means it's entirely retroactive: resubmitting the same topic for an already-finished episode that predates this feature (no `"youtube"` key yet) generates it on that resume alone, without `--force` and without regenerating anything else -- confirmed live against a previously-completed 62-minute episode, where every narration/image/video-build step was a pure cache hit except this one new call.

**Access**: `GET /episodes/{slug}/youtube` (404 until generated) returns the stored dict as-is; `_episode_progress()`'s `youtube_metadata_ready` boolean (on `/episodes` and `/episodes/{slug}`) is what the Configuration UI checks to decide which button to show on that episode's row -- clicking "YouTube metadata" (when ready) fetches and expands title/category/tags/description/chapters inline (cached client-side per slug so the panel survives the episode list's own auto-refresh, see [Configuration UI](#configuration-ui)).

**Generating on demand**: `POST /episodes/{slug}/youtube/generate` (optional `{"force": true}`) calls the same `youtube_metadata.generate()` the pipeline itself calls, but directly -- independent of running a job -- for an episode that predates this feature, had it disabled at generation time, or whose one Ollama call failed. This is the same pattern as the voice-preview endpoint calling `voice_samples.get_or_create()` directly rather than through a job. The Configuration UI shows a "Generate YouTube metadata" button in place of the toggle on any episode row where `youtube_metadata_ready` is still false; a "Regenerate metadata" button inside the expanded panel calls the same endpoint with `force: true` for an episode that already has it. A 502 means the underlying Ollama call failed or the episode has no completed segments yet -- check `history-api`'s logs for the actual error.

**Tests**: `tests/test_youtube_metadata.py` (timestamp formatting, chapter arithmetic against a hand-checked timeline, generate/cache/force/no-segments/Ollama-failure behavior), `tests/test_prompts_youtube.py` (system/tool/user builders), `tests/test_pipeline_youtube.py` (the enable/disable and caching-integration lifecycle above), and `tests/test_api_youtube_endpoint.py` (both the on-demand `/generate` endpoint and the `/youtube` read endpoint) plus the `youtube_metadata_ready` cases in `tests/test_api_episode_progress.py` (API-level). Run the same way as the pitch tests (see [Narrator Pitch](#narrator-pitch)). Verified live against a real 3-segment episode (`the-great-emu-war`) that predated this feature -- `POST /episodes/the-great-emu-war/youtube/generate` produced correct title/category/chapters in one call, with no job or pipeline run involved.

### Publishing metadata to a real YouTube video

Generating metadata (above) and pushing it to an actual uploaded video are separate steps -- this app never uploads video files to YouTube itself, only updates a video's title/description/tags/category once it already exists there (via the YouTube Data API v3's `videos.update`), given that video's ID.

**One-time OAuth setup** (per Google account/channel, not per episode):

1. In [Google Cloud Console](https://console.cloud.google.com/), enable the **YouTube Data API v3** on a project, then create an OAuth 2.0 Client ID of type **Desktop app** under APIs & Services -> Credentials. (A **Web application** type client will fail with `redirect_uri_mismatch` unless `http://localhost:8090` is added to its Authorized redirect URIs by hand -- Desktop-app clients accept any localhost loopback port automatically, which is what the script below assumes.)
2. If the OAuth consent screen is in **Testing** mode (the default until you publish it), add your own Google account under **Test users** first, or the consent step fails with "Access blocked."
3. Put the client ID/secret in `/srv/apps/history-generator/.env` (`chmod 600`, never committed):
   ```
   YOUTUBE_CLIENT_ID=....apps.googleusercontent.com
   YOUTUBE_CLIENT_SECRET=GOCSPX-...
   ```
4. Run `python3 youtube_oauth_setup.py` from `/srv/apps/history-generator` on the server. It starts a temporary listener on `http://127.0.0.1:8090` and prints a Google consent URL. Since the server is headless, open an SSH tunnel from your own machine first (`ssh -L 8090:localhost:8090 <user>@<server>`), then open the printed URL in a browser on your machine and approve access. The script captures the redirect, exchanges the code for a refresh token, and appends `YOUTUBE_REFRESH_TOKEN=...` to the same `.env` file. This is the only interactive step -- the refresh token doesn't expire (as long as the consent screen stays in Testing mode with this account as a test user, or is later published) and the pipeline never re-runs this script on its own.
5. `docker compose up -d --build history-api` to pick up the three new env vars (`compose.yaml` reads them via `${YOUTUBE_CLIENT_ID}` etc., the same `.env`-substitution mechanism already used for `NTFY_TOKEN`).

**Publishing**: `POST /episodes/{slug}/youtube/publish` with `{"video_id": "<youtube-video-id>"}` (the string after `v=` in the video's URL) -- `src/youtube_publish.py:update_video_metadata()` mints a short-lived access token from the refresh token, fetches the video's *current* snippet first and merges in the new title/description/tags/categoryId (rather than replacing the whole snippet from scratch, since `videos.update` overwrites the entire object -- this avoids silently wiping fields like `defaultLanguage` that this app never touches), and appends the chapters block to the description verbatim (YouTube parses chapter markers straight out of description text, there's no separate API field for them). On success, `video_id` and a `published_at` timestamp are saved back into the manifest's `"youtube"` block. Category names map to YouTube's stable US numeric category IDs (`Education` -> 27, `Science & Technology` -> 28, `Entertainment` -> 24 -- the only three `propose_youtube_metadata`'s tool schema can produce), falling back to Education if something unexpected comes back. A 503 (not a stack trace) means the three env vars above aren't configured yet; a 502 means the YouTube API call itself failed (bad video ID, revoked consent, quota exceeded, ...) -- the response body is Google's own error text.

The Configuration UI's "YouTube metadata" panel (see [Access](#youtube-metadata) above) includes a video-ID field and "Publish to YouTube" button that calls this endpoint directly.

**Tests**: `tests/test_youtube_publish.py` (access-token refresh, snippet fetch/merge, chapter-appending, category mapping and its fallback, and both HTTP-failure paths, all against a fake `requests` module -- no live Google API calls in the test suite) and the publish-endpoint cases in `tests/test_api_youtube_endpoint.py` (503 when unconfigured, 404s, success storing `video_id`/`published_at`, 502 passthrough).

## Resumability

The manifest (`manifest.json`) tracks per-segment status (`pending` / `complete` / `failed`). Re-running the same topic without `--force`:

- Skips any segment whose script + audio files already exist and are valid.
- Continues generating from the first incomplete segment.
- If total narration duration is still short of the target after exhausting the outline, asks Qwen for additional non-overlapping segment topics and keeps going (up to 8 outline extensions).
- Skips the ambient mood design call and re-rendering the ambient bed if `manifest.json` already has an `"ambient"` entry from a prior run (so resuming doesn't re-roll the mood or re-synthesize audio).
- Re-checks every *complete* segment's pitch on every run (not just newly-generated ones) and re-shifts + rebuilds just that segment's video if `--pitch` differs from what it was last built with — see [Narrator Pitch](#narrator-pitch). Pitch is a post-process layered on top of Kokoro's output, so this takes effect without re-synthesizing speech.
- Also compares `--voice`/`--speed`/`--sentence-gap` against the manifest's last-used values on every run; if any changed, every already-complete (or failed) segment is reset to `pending` and its narration audio, pitch-shifted audio, and per-segment video are deleted, so the next pass re-synthesizes them at the new setting. Unlike pitch, all three are baked directly into how Kokoro's output is produced, so there's no cheaper way to apply a change than regenerating the narration itself — see [Voice/speed/sentence-gap caching](#voicespeedsentence-gap-caching). Scripts are never touched or regenerated.
- Re-prepares background music only when something it depends on actually changed (track, level, fades, or episode duration) or the selected file's content changed on disk — see [Background Music](#background-music). Disabling music after enabling it removes the stale soundtrack rather than leaving it baked into a future narration-only render.
- Compares `--visual-style` against the manifest's last-used value; if changed, every complete segment's per-segment video (and the cached gap/background-mix clips) are deleted so they're rebuilt with the new background — narration, scripts, and the chosen math visualization's own parameters (once selected) are untouched. See [Math Visualizations](#math-visualizations).
- When `visual_style="images"`, each complete segment's AI-generated stills (and the prompts that produced them) are kept once generated and reused on resume, regenerated only when missing, incomplete, or `--force`'d — see [AI-Generated Segment Images](#ai-generated-segment-images).
- Reads `domain` once, from the manifest if already set — unlike every setting above, a different `--domain` on a resume is logged and ignored rather than applied, since domain changes what gets written (script content), not just how it's spoken or displayed, so there's no cheap partial-invalidation path. See [Content Domains](#content-domains).

This means a long ~60-minute run can be safely interrupted (Ctrl-C, reboot, crash) and resumed with the exact same command. `--force` wipes all of this, including the chosen ambient mood — a forced re-run may pick a different mood on the next call.

## Duration control

The pipeline never assumes N segments ≈ N × 75 seconds. After every segment's audio is generated, `ffprobe` measures its actual duration, which is recorded in `manifest.json` and summed to decide whether more segments are needed. The final MP4 will typically run slightly *over* the target, since generation stops after the segment that crosses the threshold rather than mid-segment.

**Speed/gap-aware script budgeting**: the per-segment script prompt doesn't ask for a fixed "150-220 words" regardless of settings — `src/prompts.py:estimate_target_words()` scales the requested word count by `speed` (a slower narrator needs *fewer* words to fill the same real-world duration, since the same word count simply takes longer to speak — this exact miscalibration once produced a 90.8s segment against a 60s target at `speed=0.85`) and by `sentence_gap_seconds` (each sentence-gap pause eats into the time budget without adding words, so more/longer gaps mean fewer words requested). `pipeline.py:estimate_segment_target_seconds()` also reserves the projected inter-segment gap time before dividing the remaining budget across the planned segment count, so `--duration` targets the *finished video's* length, not just the sum of narration. Qwen doesn't follow word-count guidance exactly, so individual segments still run somewhat over their own sub-target — this narrows the error, it doesn't eliminate LLM length variance. The run's final summary reports segments completed, inter-segment gaps inserted, and both the estimated and `ffprobe`-measured actual final duration.

## Video

Phase 1 video is deliberately simple: a static 1920×1080 dark background with the episode title and current segment title as text overlays (DejaVu Sans Bold, baked into the image), synced to that segment's narration audio, encoded H.264/AAC. Segments (and any gap clips) are joined with FFmpeg's concat *filter* (`src/video.py:_concat_clips()`), re-encoding (not stream copy) with `+faststart`, so the final file has consistent audio sync across segment boundaries and starts playback immediately in browsers/players instead of waiting to read the moov atom at the end of the file.

Two FFmpeg duration pitfalls were found and fixed here, both worth knowing about if this code is touched again:

- Each segment's video stream is explicitly cut with `-t <probed narration duration>` rather than relying on FFmpeg's `-shortest` alone — with an infinite `lavfi` color source behind a `drawtext` filter chain, `-shortest` was found to let the video stream run ~1.8-2s longer than the narration audio (a silent tail with the title still on screen). See `tests/test_video_segment_duration.py`.
- Joining is done with the concat *filter*, not the concat *demuxer* (`-f concat`) used originally: the demuxer was found to badly miscalculate output duration once **two or more** short clips (e.g. segment gaps under ~2s) appear in the sequence — a true ~78s sequence (3 segments + 2 gaps) came out at 113s on this project's FFmpeg build (7.1.5); a single gap was fine, which is why it went unnoticed until a 3+-segment, gap-enabled episode was actually rendered end-to-end. The filter approach concatenates decoded frames within one FFmpeg process instead of stitching containers by timestamp, and doesn't have this failure mode. Because segment clips and the gap clip don't necessarily share the same audio sample rate/channel layout (segments inherit Kokoro's, currently 24kHz mono; the gap clip is generated at 48kHz stereo), each input's audio is explicitly normalized (`aformat`) before concatenation rather than relying on implicit format negotiation. See `tests/test_video_gap.py::test_two_gaps_do_not_inflate_final_duration`.

AI-generated per-segment images (`visual_style="images"`, see [AI-Generated Segment Images](#ai-generated-segment-images)) and cross-fading between them are implemented. Ken Burns pans, subtitles, and transitions beyond a simple cross-fade are still not implemented — the code path (`src/video.py`) remains structured so those can be added later without touching the narration/TTS pipeline.

## Narrator Pitch

`pitch_semitones` (`--pitch` CLI, `"pitch_semitones"` API/chat tool, default `0.0`, range **-4.0 to +4.0**) shifts the narrator's pitch independently of `speed` — negative is deeper/more resonant, positive is higher:

| Value | Effect |
|---|---|
| -2 | Noticeably deeper voice |
| -1 | Slightly deeper voice |
| 0 | Original Kokoro voice |
| +1 | Slightly higher voice |
| +2 | Noticeably higher voice |

It is **not** a Kokoro parameter — Kokoro only ever sees `voice` and `speed`, exactly as before. Instead, `src/pitch.py:shift()` runs each segment's raw Kokoro narration through FFmpeg's `rubberband=pitch=<factor>:tempo=1.0` filter after TTS but before that segment's video is built, where `pitch_factor = 2 ** (pitch_semitones / 12)` and `tempo=1.0` keeps duration/speaking speed unchanged. `pitch_semitones == 0` skips this entirely — no extra re-encoding, no behavior change for existing episodes.

**Caching**: the raw Kokoro output (`audio/NNN.mp3`) is never touched or re-synthesized by a pitch change — only a separate `audio/NNN.pitch.mp3` is written. `pipeline.py:apply_pitch_to_segments()` runs on every generation call (including resumes) and compares each already-*complete* segment's last-applied pitch against the currently-requested one: a mismatch re-shifts that segment's narration and deletes its now-stale `video/NNN.mp4` so `video.py` rebuilds just that segment's video from the new narration — without going back to Ollama or Kokoro. An unchanged pitch (including staying at `0`) is a true no-op, so switching pitch back and forth between previously-used values only costs one FFmpeg pass per switch, not a full re-render.

**Requirements**: needs an FFmpeg build with `--enable-librubberband` (the project's own Dockerfile image has it; confirm with `docker exec history-api ffmpeg -hide_banner -filters | grep rubberband`). If it's missing and a nonzero pitch is requested, generation fails fast with a clear `[error]` before any segments are processed — it never silently ships an unadjusted video.

**Tests**: `tests/test_pitch.py` (validation bounds/finiteness, that `shift()` preserves duration and audibly changes pitch in the expected direction, verified via a synthesized tone and zero-crossing frequency estimation) and `tests/test_pipeline_pitch.py` (the caching/invalidation lifecycle above) and `tests/test_api_pitch.py` (API-level validation). Run them via:

```bash
cd /srv/apps/history-generator
docker build -t history-generator:local .
docker run --rm -v "$PWD/tests:/app/tests:ro" --entrypoint sh history-generator:local \
  -c "pip install --quiet pytest && cd /app && python3 -m pytest tests -v"
```

(`requirements-dev.txt` lists `pytest`; it's for running `tests/` locally/in this throwaway container, not part of the production image.)

### Voice/speed/sentence-gap caching

Unlike pitch, `voice`, `speed`, and `sentence_gap_seconds` are all baked directly into how the synthesized audio is produced (voice/speed by Kokoro itself; sentence gaps by whether the segment is synthesized as one Kokoro call or several — see [Sentence Gaps](#sentence-gaps)), so there's no post-process that can apply a change to already-generated narration — it has to be re-synthesized. `pipeline.py:apply_narration_params_to_segments()` runs on every generation call (including resumes), before any segment is processed, and compares all three against the values recorded in `manifest.json` from the last run:

- Unchanged: a true no-op — no files touched, no segment reprocessed.
- Changed (any one of the three): every segment that isn't already `pending` (`complete` or `failed`) is reset to `pending`, its `duration`/`error` are cleared, and its raw narration (`audio/NNN.mp3`), pitch-shifted narration (`audio/NNN.pitch.mp3`, if any), and per-segment video (`video/NNN.mp4`) are deleted. The next pass through the normal segment loop regenerates all of it — new script text is **not** generated; only Kokoro synthesis, any pitch shift, and the segment video are redone. `--segment-gap` deliberately isn't part of this check: it only affects the final assembly step (see [Segment Gaps](#segment-gaps)), never narration.

This means switching `--speed`/`--voice`/`--sentence-gap` on an existing episode no longer needs manual file surgery — just rerun `generate.sh` (without `--force`, which would also throw away the outline and scripts) with the new value and it re-synthesizes every segment automatically.

**Tests**: `tests/test_pipeline_narration_params.py` (no-op when unchanged, invalidation on voice, speed, or sentence-gap change, pitched-audio/pitch-tracking cleanup, pending/failed segments handled correctly, and that `--segment-gap` alone never triggers a reset). Run the same way as the pitch tests above.

## Ambient Audio

Unlike the narration voice, there's no library of licensed/recorded ambient music anywhere in this stack. Instead, `qwen3:32b` is given a real Ollama tool (`src/ambient.py:AMBIENT_TOOL`, called via `src/ollama_client.py:chat_tool`) and acts as a sound designer: given the episode topic and title, it calls `design_ambient_bed` with parameters for a small procedural synth chain — drone frequency, a stacked chord (in semitone offsets), oscillator shape, a noise color/level, a lowpass cutoff, a slow tremolo, and an echo/reverb amount. There is no manual mood picklist; the model chooses the mood itself (e.g. "epic and triumphant" for a war, "somber and reflective" for a tragedy) and those choices are recorded in `manifest.json` under `"ambient"`.

`src/ambient.py:render()` turns those parameters into an actual audio file with `ffmpeg` (`sine`/`aevalsrc` oscillators, `anoisesrc`, `lowpass`, `tremolo`, `aecho`), rendered directly to the episode's total narration length — no looping, since the lavfi sources are procedurally infinite. `src/video.py:_mix_background()` then mixes that bed (and/or background music, see below) under the narrated video's audio at a low level (`amix`, `duration=first` so background tracks are trimmed/never extend the video, plus `alimiter` as a clipping safeguard) as a final pass after the narrated video is assembled, re-encoding only the audio track (`-c:v copy`).

If the model doesn't call the tool (older/incompatible model, malformed response, Ollama error) or `ffmpeg` fails to render the bed, generation falls back to a fixed neutral preset (`ambient.py:DEFAULT_PARAMS`) or, if even that render fails, continues with no ambient audio at all — this never aborts an episode.

Disable it with `--no-ambient` (CLI), `"ambient": false` (API/chat tool), or set `AMBIENT_ENABLED=false` in `compose.yaml` to change the default for a service.

## Background Music

Unlike the procedural ambient bed, background music is **real, human-curated audio** from a local library — never generated, downloaded, or picked by the model at generation time. It's off by default (`music: false` / `--no-music`), since it needs at least one track a human has actually reviewed and approved before it can be auto-selected.

### The library and its catalog

The library lives on the host at `/srv/media/audio/music/` (separate from `/srv/media/audio/effects/`, which this pipeline doesn't touch), organized into category folders (e.g. `sleep-ambient/`). It's mounted **read-only** into `history-generator` and `history-api` at `MUSIC_LIBRARY_DIR` (default `/app/audio-library/music`) — neither service ever writes, renames, or deletes a source file.

A `catalog.json` inside the library is the source of truth for what tracks exist and whether they're approved. Each entry (`src/music_catalog.py`) looks like:

```json
{
  "id": "8deebe159302",
  "title": "leberch-ambient-578724",
  "file": "sleep-ambient/leberch-ambient-578724.mp3",
  "category": "sleep-ambient",
  "tags": ["sleep-ambient"],
  "mood": "sleep-ambient",
  "energy": "very-low",
  "vocals": false,
  "percussion": false,
  "sleep_safe": true,
  "creator": null,
  "source_url": null,
  "license": null,
  "license_file": "sleep-ambient/some-license.txt",
  "duration_seconds": 152.03,
  "fingerprint": "8deebe1593024d5ea856d1934dd42af631b84d9a242ae2ea73b3f7acb5630f5d"
}
```

`id` is derived from the file's content hash (`fingerprint[:12]`), so it's stable across rescans as long as the audio itself doesn't change. `fingerprint` is a full SHA-256 of the file's bytes, used both for catalog dedup and for detecting a file swapped in under the same path later (see [Resumability](#resumability) below).

### Scanning the library

Run the scanner after adding, removing, or replacing files:

```bash
cd /srv/apps/history-generator
docker compose run --rm music-scan
```

(`music-scan` mounts the library **read-write**, unlike the generation services — see `compose.yaml`. It never touches audio files, only `catalog.json`.) It reports what it added, what changed (content-changed files get `sleep_safe` reset to `false`), what's on record but missing on disk (kept, not deleted), and any byte-identical duplicates it found (cataloged once, not twice, so they don't collide on the same derived `id`).

New tracks are added as **unreviewed**: `sleep_safe: false`, `energy`/`vocals`/`percussion`: `null`. The scanner never infers suitability or a license from a filename or folder — for Pixabay-style downloads it'll pick up a matching `*-license.txt` next to the track (by shared numeric ID) and record `license_file` plus whatever `creator`/`source_url` facts that certificate actually states, but it never fills in `license` or flips `sleep_safe` itself. **A human has to listen to each new track and edit `catalog.json`** to set `sleep_safe: true`, `vocals`, `percussion`, and `energy` (`"very-low"`/`"low"`/...) before it's eligible for automatic mood-based selection. Until then, it's only usable by passing its exact `music_track_id` (which bypasses the safety filters — you're vouching for that one file yourself).

### Generation parameters

`--music` / `--no-music` (CLI, default off), `"music": true/false` (API/chat tool). When enabled:

- `--music-mood <category>` (default `sleep-ambient`) — filters the catalog to tracks whose `category`/`tags` match, further restricted to only `sleep_safe: true, vocals: false, percussion: false, energy: very-low|low` tracks. Selection among the remaining candidates is **deterministic per episode** (seeded by the episode slug via `src/music.py:resolve_track()`), so re-running the same episode doesn't pick a different track.
- `--music-track-id <id>` — selects that exact catalog track, bypassing the mood filters and the `sleep_safe`/`vocals`/`percussion`/`energy` gate entirely (existence on disk is still checked).
- `--music-level <dBFS>` (default `-25.0`, range **-40.0 to -6.0**) — final level of the music bed.
- `--music-fade-in <seconds>` / `--music-fade-out <seconds>` (defaults `8.0` / `20.0`, must be ≥ 0) — automatically capped to half the episode's duration each, so absurd values can't error out or eat the whole track.
- `--music-library-dir <path>` — override the library mount point (rarely needed).

If `music` is enabled and no track can be resolved (missing library, empty/no catalog, unknown `music_track_id`, or no `sleep_safe`-approved track for the requested mood), **generation fails with a clear `[error]` and no video is produced** — unlike ambient, this is never a silent fallback, since you explicitly asked for a specific soundtrack.

### How it's built

`src/music.py:prepare()` runs a single `ffmpeg` pass per episode: `-stream_loop -1` on the source track (looping it if shorter than the narration, trimming it if longer — the same code path handles both, cut off cleanly at `-t <duration>`), a one-pass `loudnorm` for consistent perceived loudness regardless of the source file's own mastering, the configured `volume=<level>dB`, and `afade` in/out. The source file is opened read-only and never modified; the result is written to `video/.music.wav`. `src/video.py` then mixes it in exactly like the ambient bed (see above) — narration, ambient, and music are summed with `amix` plus an `alimiter` safety net, so all four combinations (neither / ambient only / music only / both) just work, and nothing is ever mixed per-segment (avoiding restarts at segment boundaries — one continuous bed across the whole episode).

### Resumability and caching

Music preparation is cached in `manifest.json` under `"music"` (enabled, requested mood, selected `track_id`/`file`, a **live-computed** fingerprint of the resolved file, level, fades, the duration it was prepared for, and the prepared file's path). On every run (including resumes), `src/pipeline.py:apply_music()` re-hashes the currently-selected file on disk and compares against everything above — if all of it matches, `video/.music.wav` is reused as-is with **no** `ffmpeg` call; if anything differs (a different track, level, fades, a grown episode duration, or the same file's *content* replaced at the same path without rescanning), it's regenerated. Disabling music after it was enabled removes the stale `.music.wav` and clears the manifest flag, so a subsequent narration-only render can never accidentally ship the old soundtrack. None of this ever touches the script, raw or pitch-shifted narration, or per-segment videos — only `video/.music.wav` and the final assembly step.

**Tests**: `tests/test_music_catalog.py` (scan discovery/dedup/missing-file handling/metadata preservation/license-certificate parsing), `tests/test_music.py` (selection — explicit id vs. mood-filtered auto-select, determinism, path-traversal rejection — plus `prepare()`'s loop/trim/fade/level behavior), `tests/test_pipeline_music.py` (the full cache-invalidation lifecycle, disable-then-reuse safety, and that it never touches narration files), and `tests/test_video_music_ambient_combos.py` (all four ambient/music on/off combinations). All synthetic (generated tones), no live Kokoro or real copyrighted audio required. Run them the same way as the pitch tests (see [Narrator Pitch](#narrator-pitch)).

## Segment Gaps

`segment_gap_seconds` (`--segment-gap` CLI, `"segment_gap_seconds"` API/chat tool, default **1.5**, range **0 to 10**) inserts a silent pause between consecutive segments in the final video, with background music/ambient continuing to play through it rather than cutting out. It's a gap *between* segments only — narration is never split, so a sentence that flows into the next one is never interrupted by a forced pause. `0` disables it entirely (segments are concatenated back-to-back, matching the original behavior).

**How it's built**: `src/video.py:_build_episode_video()` builds one small silent+blank clip (`video/.gap.mp4`, same 1920x1080/30fps/h264+aac format as segment clips) per call and inserts it into the concat list between every pair of segments (not before the first or after the last). It's rebuilt on every run rather than cached — it's a sub-second encode, so there's nothing worth caching. A single-segment episode never gets a gap, since there's no "between" to insert one into.

**Duration accounting**: `N` complete segments contribute `N-1` gaps. `src/pipeline.py:run()` computes the full video length (narration total + total gap time) and uses *that* — not just the narration total — as the duration passed to both the ambient bed renderer and `apply_music()`, so the background bed is prepared long enough to cover the gaps instead of running out early and going silent near the end. Background music re-prepares automatically when this duration changes (see [Background Music → Resumability and caching](#resumability-and-caching)); the procedural ambient bed does not auto-extend on a duration change alone (existing limitation, not specific to gaps) — use `--force` if you change the gap on an episode that already has a rendered ambient bed and want it stretched to match.

**Tests**: `tests/test_video_gap.py` (validation bounds, gap-free single-segment case, final-duration accounting, and that background music is audible in the middle of the gap) and `tests/test_api_gap.py` (API-level validation). Run the same way as the pitch tests (see [Narrator Pitch](#narrator-pitch)).

## Sentence Gaps

`sentence_gap_seconds` (`--sentence-gap` CLI, `"sentence_gap_seconds"` API/chat tool, default **0.5**, range **0 to 2**) inserts a pause *within* a segment, between sentences, independent of `--segment-gap` (which only pauses *between* segments). The goal is relaxed, natural pacing, not a mechanical pause after every sentence — so it deliberately does not touch sub-sentence punctuation (commas, semicolons) and never fires inside an abbreviation (`Dr.`, `U.S.`, `e.g.`) or a decimal number (`3.14`). `0` disables it entirely: the segment is synthesized in a single Kokoro call, byte-for-byte the same as before this feature existed.

**How it's built**: Kokoro has no parameter for pause length, so `src/sentence_gap.py` gets a consistent, configurable pause by splitting the script into sentences (`split_sentences()` — a conservative regex tokenizer, not a general NLP model), synthesizing each one with its own Kokoro call, silence-trimming both ends of each resulting clip (`ffmpeg`'s `silenceremove`, forward and reversed), and concatenating the trimmed clips with exactly `sentence_gap_seconds` of generated silence between them. Trimming first is what keeps the pause from being "whatever natural pause Kokoro happened to leave, plus the configured gap" — every boundary gets normalized to exactly one pause of the requested length. A single-sentence script also skips all of this and makes one Kokoro call, same as `0`.

**Duration accounting**: sentence-gap pauses are baked into the segment's own narration audio file, so `ffprobe`'s measured segment duration (used for `manifest.json` and the running narration total) already includes them — no separate bookkeeping needed, unlike segment gaps.

**Caching**: changing `sentence_gap_seconds` re-synthesizes affected segments' narration from scratch (more Kokoro calls, one per sentence, not just a cheap post-process) — see [Voice/speed/sentence-gap caching](#voicespeedsentence-gap-caching). Scripts are never regenerated.

**Tests**: `tests/test_sentence_gap.py` (validation bounds, sentence-splitting correctness against abbreviations/decimals/questions/exclamations, and `synthesize_segment()`'s call-count and duration behavior at zero/single-sentence/multi-sentence gaps, using synthetic tones in place of live Kokoro) and `tests/test_api_sentence_gap.py` (API-level validation). Run the same way as the pitch tests (see [Narrator Pitch](#narrator-pitch)).

## Math Visualizations

`visual_style` (`--visual-style` CLI, `"visual_style"` API/chat tool, default **`static`**, one of `static`/`math`) swaps the plain dark segment background for an animated mathematical visualization: stacked sine/cosine waves, a Fourier-series approximation of a square or sawtooth wave, or a point tracing a parametric (Lissajous-style) curve with a fading trail. `static` is the original behavior, unchanged.

**Selection**: which family and its specific parameters (frequencies, colors, curve ratios, ...) is picked by `src/math_visual.py:select_visual(slug)` — a plain seeded random choice (`hashlib.sha256(slug)` seeding Python's `random`), not an LLM call, deterministic per episode. It's selected once, the first time `visual_style` becomes `"math"` for an episode, then stored in `manifest.json` under `"visual"` and reused on every subsequent run — resuming or rebuilding an episode always reproduces the same background. Toggling `visual_style` back to `static` and later back to `math` reuses the original selection rather than re-rolling it. The only way to get a *different* random pick is `--force` (which rebuilds the whole episode from scratch anyway — there's no separate "reroll the visual" flag, matching how `--force` already reshuffles the ambient mood).

**Rendering**: no external image/plotting library is used — each visualization is drawn entirely by FFmpeg's `geq` (generic-equation) video filter, which computes every output pixel's r/g/b directly from a math expression of its position and the frame's time (`src/math_visual.py`). A ~20-second clip is rendered once per episode and cached at `video/.math_bg.mp4` (existence-check caching, like the ambient bed — never re-rendered just because narration/music/other settings changed), then looped (`-stream_loop -1`) in `video.py` to cover however long each segment and gap clip actually runs, including sentence-gap pauses (already baked into the narration audio) and inter-segment gaps (the gap clip uses the same looped background). Every animated phase term is built as `cycles * T / loop_seconds` with an integer `cycles`, so the clip's last frame's phase exactly equals its first frame's — the loop has no visible jump when it wraps. The background loop *restarts* (from its own phase 0) at each segment/gap boundary rather than staying phase-continuous across the whole episode; since segment boundaries are already hard content cuts (new title, new narration), this was a deliberate simplicity/caching tradeoff, not an oversight — true whole-episode continuity would make every segment's render depend on the exact durations of every segment before it, breaking per-segment caching for a subtle visual difference. See the "restarts, not phase-continuous" note in `video.py:build_episode_video()`.

`geq` is slow at full resolution — a full 1920x1080/30fps/20s render was measured taking 8+ minutes and climbing. The clip is instead rendered at a quarter resolution (`math_visual.RENDER_RESOLUTION`, 480x270) and upscaled (`scale=...:flags=bilinear`) when composited with the segment's title text, cutting render time to single-digit seconds up to ~25s for the busiest family (`trace`, which sums several trailing-dot terms per pixel) — a soft, slightly-blurred-on-upscale background is not a problem for what's meant to be a calm, non-distracting layer. A translucent band is drawn behind each line of title text (`drawbox`) before the math background gets busy enough to hurt legibility.

**Caching/invalidation**: `pipeline.py:apply_visual_to_segments()` compares the requested `visual_style` against the manifest's last-used value on every run; an unchanged value (including staying `static`) is a true no-op. A change deletes every complete segment's per-segment video (`video/NNN.mp4`) plus the cached gap clip, math background, and pre-mix file, without touching narration, scripts, or audio — only the video depends on the background. This is the same *shape* of invalidation as `--pitch` (see [Narrator Pitch](#narrator-pitch)), scoped to video only.

**Tests**: `tests/test_math_visual.py` (selection determinism/variation, visual-style validation, and — independent of any actual FFmpeg render — direct verification that each family's phase formula evaluates identically at `t=0` and `t=loop_seconds`, which is the actual guarantee behind "the loop doesn't jump"), `tests/test_pipeline_visual.py` (the cache-invalidation lifecycle above), `tests/test_video_math_visual.py` (real, small end-to-end renders: correct final duration, background-caching behavior), and `tests/test_api_visual.py` (API-level validation). Run the same way as the pitch tests (see [Narrator Pitch](#narrator-pitch)) — this suite takes noticeably longer than the others (~20-30s) because of the handful of real FFmpeg renders it includes.

## AI-Generated Segment Images

`visual_style="images"` (the third option alongside `static`/`math`, see [Math Visualizations](#math-visualizations)) replaces the segment background with a short sequence of AI-generated illustrations, cross-faded into one another, covering that segment's full narration. Unlike the math visualizations (one seeded-random choice per episode, no LLM involved), this is on-topic per segment: an Ollama tool call reads the segment's own script and proposes concrete visual scenes, then a local FLUX.1-schnell diffusion model renders each one.

**Why a separate service**: image generation is the first real GPU diffusion workload in this stack (everything else — math visuals, ambient audio, gaps, mixing — is procedural FFmpeg, no ML). It runs as its own Docker Compose project, `/srv/apps/comfyui`, running [ComfyUI](https://github.com/comfyanonymous/ComfyUI) (image `yanwk/comfyui-boot:cu128-slim`, chosen because its bundled PyTorch 2.11.0+cu128 supports the RTX 5090's Blackwell architecture natively — the stable PyTorch releases used elsewhere in this stack don't yet have `sm_120` kernels, which is exactly why Kokoro TTS runs on CPU; see [GPU / VRAM](#gpu--vram)). `comfyui`'s persistence root (`./data:/root`, the image's own convention) holds the model weights on the host, off the image layer, surviving container recreates: `flux1-schnell-fp8.safetensors` (~17GB), `clip_l.safetensors` + `t5xxl_fp8_e4m3fn.safetensors` (text encoders), and `ae.safetensors` (VAE). `comfyui` joins only `comfyui_internal` (see [Architecture](#architecture)) — never `edge`, no published port.

**Why FLUX.1-schnell**: Apache-2.0 licensed, and a 4-step distilled model, so a single 1024×576 image renders in a few seconds on the 5090 rather than the 20-50 steps a full diffusion model needs. Its official HuggingFace repo is nonetheless gated for some files (the VAE) even though the weights themselves are unrestricted — obtaining `ae.safetensors` required an authenticated HuggingFace token with the repo's license explicitly accepted (a separate step from just creating the token); the ungated `Comfy-Org` mirror was used for the main checkpoint instead. The HF token used for that one-time download lives in `/srv/apps/comfyui/.env` (`chmod 600`, not committed anywhere) and is never needed again once the weights are on disk.

**Prompt derivation**: `src/prompts.py:build_image_prompts_system()`/`build_image_prompts_tool()` ask Ollama (`src/segment_images.py:_propose_prompts()`, a `chat_tool` call like `ambient.py`'s mood design) to propose one concrete visual scene per image, from that segment's own title/summary/script text, in a style drawn from the active domain's `image_style` string (see [Content Domains](#content-domains)) — e.g. history renders "cinematic, photorealistic ... painterly, accurate period detail", math renders "clean minimalist abstract geometric ... no equations or text". The system prompt explicitly forbids asking for any text/labels/diagrams in the image, since diffusion models render text as garbled nonsense; the segment/episode titles are drawn separately as a text overlay at video-assembly time, same as every other visual style. If the Ollama call fails outright, a plain fallback (`"<segment title>, <domain's image_style>"`) is used instead of failing the segment.

**How many images per segment**: `src/segment_images.py:images_for_duration()` — one image roughly every 15 seconds of that segment's actual (`ffprobe`-measured) narration duration, clamped to 2-6 images. This runs *after* narration synthesis (unlike the math visual's up-front selection), since it depends on the real measured duration, not the requested target.

**Rendering**: each proposed scene is rendered once via ComfyUI's `/prompt` API (`src/image_client.py:generate_image()`) — a hand-built node graph (`UNETLoader -> DualCLIPLoader -> VAELoader -> CLIPTextEncode x2 -> EmptySD3LatentImage -> KSampler -> VAEDecode -> SaveImage`) submitted as JSON, then polled via `/history/{prompt_id}` until complete and fetched via `/view`. Every node/field name was verified live against a running ComfyUI's `/object_info/{NodeName}` before being hand-written, rather than guessed — ComfyUI rejects an unknown field with a 400 at submit time, not a mysterious failure later. Images render at 1024×576 (16:9, matching the pipeline's video aspect ratio) with schnell's own recommended settings (4 steps, `cfg=1.0`, `euler`/`simple`) — a negative prompt forbids text/watermarks/blur/deformities. Each image's seed is a deterministic hash of `(slug, segment number, image index)`, so a resumed episode's images are the same shot even if regenerated.

**Strictly sequential GPU scheduling**: `history-api` can run multiple episode jobs concurrently (one background thread per slug), and each job now calls both Ollama and ComfyUI against the same physical GPU. `src/gpu_lock.py` is a single process-wide `threading.Lock` held for the full duration of every GPU-bound call — `ollama_client.py`'s `_post()` and `image_client.py`'s submit-through-completion window both acquire it — so Ollama token generation and ComfyUI diffusion steps never run at the same time, system-wide, even across unrelated concurrent jobs. This trades some wall-clock time (a queued job's image generation waits behind another job's in-flight Ollama call, and vice versa) for not contending unpredictably for VRAM/compute on one GPU. Verified under real contention: submitting a large concurrent episode while an images-visual-style test job was mid-flight visibly serialized the two jobs' GPU calls rather than interleaving them. The CLI (`main.py`) only ever runs one job per process, so this lock is a no-op there in practice.

**The lock alone isn't enough -- VRAM residency is a separate problem from compute-time contention.** `gpu_lock` only prevents Ollama and ComfyUI from *computing* at the same instant; it does nothing about ComfyUI's model weights (~16.6GB: the FLUX UNET, both text encoders, and the VAE) staying resident in VRAM indefinitely after a generation finishes, which is ComfyUI's own default behavior (kept loaded for fast back-to-back generations). This was found the hard way: a real 60-minute `images`-style episode's outline-generation call failed after exhausting all 3 retries, `HTTPConnectionPool(... Read timed out ... read timeout=180)` -- `docker exec ollama ollama ps` showed `qwen3:32b` running a `51%/49% CPU/GPU` split, and `nvidia-smi --query-compute-apps` confirmed ComfyUI's process alone was holding 16.6GB of VRAM left over from an earlier, unrelated episode's image generation, squeezing Ollama out of the ~20-29GB it wants and forcing a CPU fallback slow enough to blow through the 180s request timeout on a 50-segment outline. The fix: `image_client.free_memory()` calls ComfyUI's `POST /free` (`{"unload_models": true, "free_memory": true}`) once per segment, right after that segment's images finish generating (`pipeline.py:apply_images_to_segments`) -- often enough that ComfyUI's weights are never parked for longer than one segment's worth of images, infrequent enough that the reload-from-disk cost isn't paid per image. It's best-effort (a failed free-memory call is logged and swallowed, never aborts the episode) since freeing VRAM a little late is far better than the episode failing outright. Note that Ollama itself won't reclaim newly-freed VRAM for an *already-loaded* model on its own -- it only re-evaluates GPU/CPU placement when it reloads (its own idle keep-alive timeout, or `docker exec ollama ollama stop qwen3:32b` to force it immediately).

**Compositing**: `src/video.py:_images_input_and_filter()` builds an FFmpeg filter chain that scales/crops each image to fill the frame and cross-fades between them (`xfade`, `transition=fade`) to land on exactly the segment's narration duration, regardless of image count — solved by treating each image's on-screen slice length as the unknown given a fixed per-transition fade duration (default 1.5s, shortened for segments with many images relative to their length so a fade never eats more than half a slice). A single-image segment skips `xfade` entirely. The same title/segment-title text overlay and legibility backdrop used for the math visualization background (see [Math Visualizations](#math-visualizations)) is drawn on top.

**Caching/invalidation**: `pipeline.py:apply_images_to_segments()` runs after narration and pitch are finalized, once per complete segment. A segment already holding the right number of images (files present, with the prompts that produced them) is left untouched on resume — regenerated only when missing, incomplete, or `--force`'d. Whenever a segment's images actually change, its now-stale per-segment video is deleted so it's rebuilt; if nothing changed, the video is left alone. Switching `visual_style` away from `"images"` behaves like switching away from `"math"` — the cached images/prompts are left on disk (harmless, reused if switched back), only the per-segment video (which depends on the active style) is invalidated. See [Resumability](#resumability).

**Tests**: `tests/test_image_client.py` (ComfyUI API client: successful generation, node-rejection/timeout/error-status/no-output failure modes, and `free_memory()`'s request payload/best-effort-swallows-failure behavior, all against a fake `requests` module, no live ComfyUI needed), `tests/test_gpu_lock.py` (the shared-lock identity and actual mutual-exclusion behavior under concurrent threads), `tests/test_segment_images.py` (image-count bounds, deterministic per-index seeding, generate/cache/force/missing-file/Ollama-failure-fallback behavior), `tests/test_prompts_images.py` (per-domain `image_style` presence, prompt/tool builders), `tests/test_pipeline_images.py` (the cache-invalidation lifecycle above, plus that `free_memory` is called exactly when a segment's images actually changed and skipped on a cache hit), and `tests/test_video_images_visual.py` (real small end-to-end renders: single-image and multi-image cross-fade duration correctness, and that `visual_style != "images"` leaves an `"images"`-carrying segment untouched). Run the same way as the pitch tests (see [Narrator Pitch](#narrator-pitch)).

## GPU / VRAM

Kokoro runs on **CPU** (see [OLLAMA.md](OLLAMA.md#text-to-speech-kokoro) for why — no official Blackwell/RTX 5090 support yet in the pre-built GPU image). FFmpeg's static-background encode is also CPU-only (no GPU filters/encoders used), as is the ambient bed's synthesis (`ambient.py:render()`, plain `lavfi` oscillator/noise filters) and the final ambient mix-in. This keeps `qwen3:32b` at 100% GPU throughout a generation run when `visual_style` isn't `"images"`, confirmed via `docker exec ollama ollama ps` during testing.

`comfyui` (used only by `visual_style="images"`, see [AI-Generated Segment Images](#ai-generated-segment-images)) is the one GPU consumer that *does* share the RTX 5090 with `qwen3:32b` — its bundled PyTorch build (unlike the stable releases elsewhere in this stack) has working Blackwell (`sm_120`) kernels, so unlike Kokoro it didn't need to fall back to CPU. Because it shares the GPU, `gpu_lock.py`'s process-wide lock forces Ollama and ComfyUI calls to run strictly one at a time rather than concurrently, system-wide, across every job `history-api` has running — see the "Strictly sequential GPU scheduling" note above. Watch VRAM with `nvidia-smi` if running an `images`-style episode alongside heavy Ollama chat traffic.

If Kokoro is later moved to GPU, only `compose.yaml` in `/srv/apps/kokoro` needs to change — the generator talks to Kokoro exclusively over `http://kokoro:8880`, so nothing in `history-generator` needs to change.

## Retries

Both Ollama and Kokoro calls retry up to 3 times with linear backoff on failure. A failed segment is marked `"status": "failed"` in the manifest (with an `"error"` field) rather than aborting the whole run — subsequent segments still get generated, and re-running the same command retries the failed one(s).

## Troubleshooting

**Output files owned by root**: shouldn't happen — `compose.yaml` sets `user: "1000:1000"`. If it does (e.g. after an image rebuild dropped that setting), fix ownership from a throwaway root container rather than `sudo chown` on the host, since the compose project doesn't run with a TTY for a sudo prompt:

```bash
docker run --rm -v /srv/apps/history-generator/output:/app/output --entrypoint sh history-generator:local \
  -c "chown -R 1000:1000 /app/output"
```

**Segment stuck failing**: check the `"error"` field on that segment in `manifest.json`, and confirm Ollama/Kokoro are reachable the same way Open WebUI reaches them (see the connectivity checks in [OLLAMA.md](OLLAMA.md)).

**Video text not rendering / ffmpeg font error**: confirm `fonts-dejavu-core` is still installed in the image (`docker run --rm --entrypoint sh history-generator:local -c "ls /usr/share/fonts/truetype/dejavu/"`).

**Tool call fails / Open WebUI can't reach history-api**: confirm the container is up and on the right networks, and test connectivity the same way as the Kokoro checks in [OLLAMA.md](OLLAMA.md):

```bash
docker ps --filter name=history-api
docker network inspect historygen_internal
docker exec open-webui curl -s http://history-api:8000/health
```

If `open-webui` isn't on `historygen_internal` (e.g. after reverting `open-webui/compose.yaml`), recreate it: `cd /srv/apps/open-webui && docker compose up -d`.

**A job says `"status": "error"`**: check `history-api`'s logs (`docker logs history-api`) for the traceback — the same retry/failure handling as the CLI applies (see [Retries](#retries)), so a single flaky segment shouldn't take down the whole job.

**Ambient bed sounds generic / always the same ("neutral", 110Hz drone, pink noise)**: that's `ambient.py:DEFAULT_PARAMS` — the fallback used when the `design_ambient_bed` tool call fails (model didn't call the tool, bad JSON, Ollama error). Check `"ambient"` in that episode's `manifest.json` — `"mood": "neutral"` with those exact default numbers means the fallback fired; the actual cause is logged as a `[warn] ambient design failed, ...` line in `history-api`'s (or the CLI's) output around the "Designing ambient audio bed..." step. A forced re-run (`--force`) will retry the tool call and may get a real mood this time.

**A nonzero `--pitch`/`pitch_semitones` fails immediately with `ffmpeg does not support the 'rubberband' audio filter`**: the image's ffmpeg wasn't built with `--enable-librubberband`. Confirm with `docker exec history-api ffmpeg -hide_banner -filters | grep rubberband` (or `docker run --rm --entrypoint ffmpeg history-generator:local -hide_banner -filters | grep rubberband` if `history-api` isn't running) — no output means it's genuinely missing and needs a different base image/ffmpeg build; this project's `python:3.12-slim` + `apt-get install ffmpeg` combination already includes it, so seeing this on an unmodified image likely means `Dockerfile` or the base image changed. `pitch_semitones=0` (the default) never touches this code path.

**`--music` fails with `no music catalog found under ... -- run scan_music.py first`**: `catalog.json` doesn't exist yet at the library mount. Run `docker compose run --rm music-scan` from `/srv/apps/history-generator` — see [Background Music](#background-music).

**`--music` fails with `no approved music tracks found for mood '...'`**: the catalog has tracks in that category, but none are marked `sleep_safe: true` (with `vocals: false`, `percussion: false`, `energy: very-low`/`low`) yet — new tracks start unreviewed on purpose. Either edit `catalog.json` by hand after listening to a track (then it'll be picked up next run, no rescan needed), or pass `--music-track-id <id>` to use one explicitly without going through the mood filters.

**`--music-track-id <id>` fails with `unknown music_track_id`**: that id isn't in `catalog.json` — list current ids with `cat /srv/media/audio/music/catalog.json | python3 -m json.tool` or rerun the scanner if you just added the file.

**`--visual-style images` fails or hangs generating images**: confirm `comfyui` is up and reachable the same way as the Kokoro checks in [OLLAMA.md](OLLAMA.md):

```bash
docker ps --filter name=comfyui
docker network inspect comfyui_internal
docker exec history-api python3 -c "import urllib.request; print(urllib.request.urlopen('http://comfyui:8188/system_stats', timeout=10).status)"
```

A `ComfyUI rejected workflow: {...}` error names the bad node/field — check `image_client.py:_build_workflow()` against a live `GET /object_info/<NodeName>` on `comfyui` if this ever fires; it means the node graph and the running ComfyUI version's schema have drifted apart. A `did not complete within ...s` timeout with `comfyui` otherwise healthy usually means it's queued behind another job's Ollama call under `gpu_lock` (see [AI-Generated Segment Images](#ai-generated-segment-images)) — check `docker logs comfyui` for actual generation progress before assuming it's stuck. If `comfyui`'s models are missing after a fresh volume (`GET /models/diffusion_models` etc. return empty lists), the weights under `/srv/apps/comfyui/data/ComfyUI/models/` need re-downloading — see the model filenames/sources in [AI-Generated Segment Images](#ai-generated-segment-images).

**An Ollama call (outline/segment/image-prompt generation) times out repeatedly, and `docker exec ollama ollama ps` shows `qwen3:32b` split across CPU/GPU instead of `100% GPU`**: this is VRAM contention with ComfyUI, not a genuine Ollama problem — see the "lock alone isn't enough" note under [AI-Generated Segment Images](#ai-generated-segment-images). `pipeline.py` already frees ComfyUI's VRAM after every segment's images, so this should be rare; if it still happens (e.g. mid-batch, or ComfyUI was used directly outside this pipeline), confirm and fix it manually:

```bash
nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv
docker exec history-api python3 -c "import urllib.request,json; urllib.request.urlopen(urllib.request.Request('http://comfyui:8188/free', data=json.dumps({'unload_models': True, 'free_memory': True}).encode(), headers={'Content-Type':'application/json'}))"
docker exec ollama ollama stop qwen3:32b   # forces a fresh, fully-GPU reload on its next request
```

**`--music` fails with `music track file missing or unreadable`**: the catalog still lists a track whose file is gone (moved, deleted, or a drive not mounted) — rerun `docker compose run --rm music-scan`, which keeps the catalog entry (for its metadata) but this confirms the file isn't currently selectable; pick a different track or restore the file.

## Common Commands

```bash
cd /srv/apps/history-generator

# rebuild after code changes
docker compose build

# run interactively / check logs of a run
docker compose run --rm history-generator --duration 300 "Ancient Rome"

# inspect an episode's progress
cat output/<slug>/manifest.json | python3 -m json.tool

# check what mood/synth params the model picked for an episode's ambient bed
cat output/<slug>/manifest.json | python3 -c "import json,sys; print(json.load(sys.stdin).get('ambient'))"

# check which music track (if any) an episode used
cat output/<slug>/manifest.json | python3 -c "import json,sys; print(json.load(sys.stdin).get('music'))"

# scan/update the background-music catalog (read-write mount, separate from generation)
docker compose run --rm music-scan

# list current catalog track ids/files/durations
cat /srv/media/audio/music/catalog.json | python3 -m json.tool

# bring up / restart just the API service
docker compose up -d history-api
docker compose restart history-api

# tail the API service's logs
docker logs -f history-api

# force an immediate Jellyfin library sync instead of waiting up to 15 min for cron
./sync-jellyfin-library.sh

# see the sync cron schedule / its run history
crontab -l
tail -f sync-jellyfin-library.log
```
