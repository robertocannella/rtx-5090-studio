This is Roberto's RTX home server.

Read these before making infrastructure changes:
- /srv/apps/docs/README.md
- /srv/apps/docs/SERVER.md
- /srv/apps/docs/JELLYFIN.md

Environment:
- Ubuntu Server 24.04
- Docker / Docker Compose
- Caddy gateway
- shared Docker network: edge
- NVIDIA RTX 5090
- media stored under /srv/media (jellyfin)
- applications under /srv/apps
- documents under /srv/docs
- public DNS managed through Cloudflare
- use vi, never nano

Rules:
- Don't expose Docker application ports publicly unless necessary.
- Route public applications through the Caddy gateway.
- Don't modify firewall/network/SSH configuration without explaining the change first.
- Don't expose credentials or API tokens.
- Update the appropriate documentation after infrastructure changes.

# Local TTS Integration for Open WebUI

## Objective

Add local text-to-speech (TTS) support to the existing Ollama + Open WebUI stack so AI-generated responses can be played as audio.

Primary use case:

* User asks Qwen for a history fact or short lesson.
* `qwen3:32b` generates the text.
* Open WebUI sends the generated text to a local TTS service.
* The TTS service generates speech.
* Audio is played through Open WebUI.

Everything should remain self-hosted.

---

# Existing Architecture

```text
Internet
   |
ai.example.com
   |
Caddy gateway :443
   |
Docker edge network
   |
open-webui :8080
   |
Docker ollama_internal network
   |
ollama :11434
   |
qwen3:32b
   |
RTX 5090
```

Public URL:

```text
https://ai.example.com
```

Existing application directories:

```text
/srv/apps/ollama
/srv/apps/open-webui
/srv/apps/gateway
```

Existing Docker networks:

```text
edge
ollama_internal
```

Important security constraint:

Ollama must NOT be added to the `edge` network and must NOT publish port `11434` to the host.

Open WebUI is the only public-facing AI service.

---

# Target Architecture

Add a local TTS service, preferably Kokoro or another OpenAI-compatible TTS implementation.

Target:

```text
                         Internet
                            |
                 ai.example.com
                            |
                         Caddy
                            |
                           edge
                            |
                       Open WebUI
                       /         \
                      /           \
       ollama_internal             tts_internal
               |                         |
            Ollama                  TTS Service
               |
          qwen3:32b
```

Open WebUI should be the only service with access to both AI backends.

Neither Ollama nor the TTS service should be directly exposed to the Internet.

---

# Step 1 — Create TTS Network

Create a dedicated private Docker network:

```bash
docker network create tts_internal
```

Verify:

```bash
docker network inspect tts_internal
```

The network should be external to the Compose projects so Open WebUI and the TTS project can both join it.

---

# Step 2 — TTS Application Directory

Create:

```bash
sudo mkdir -p /srv/apps/kokoro
cd /srv/apps/kokoro
```

Use `vi` for editing configuration files:

```bash
vi compose.yaml
```

Do not use `nano`.

---

# Step 3 — Select TTS Server

Use a maintained local TTS server that provides an OpenAI-compatible API.

Preferred model:

```text
Kokoro
```

The server should expose an endpoint compatible with:

```text
POST /v1/audio/speech
```

Before selecting a Docker image:

1. Verify the project is currently maintained.
2. Verify compatibility with the current Open WebUI TTS integration.
3. Verify the correct Docker image and version.
4. Verify the API port.
5. Verify whether GPU support is useful or necessary.
6. Verify available voices.
7. Prefer a tagged/stable image over an unpinned development image when practical.

Do NOT invent Docker image names, ports, environment variables, or API paths.

Check current upstream documentation before implementation.

---

# Step 4 — TTS Compose Design

The TTS Compose project should conceptually resemble:

```yaml
services:
  kokoro:
    image: <verified-image>
    container_name: kokoro
    restart: unless-stopped

    networks:
      - tts_internal

networks:
  tts_internal:
    external: true
```

Do not publish the TTS port to the host unless required for troubleshooting.

Normal communication should occur entirely over Docker networking.

Open WebUI should reach the service using Docker DNS:

```text
http://kokoro:<verified-port>
```

or, if required by the OpenAI-compatible configuration:

```text
http://kokoro:<verified-port>/v1
```

---

# Step 5 — Update Open WebUI Networking

Existing Open WebUI networks:

```yaml
networks:
  - edge
  - ollama_internal
```

Change to:

```yaml
networks:
  - edge
  - ollama_internal
  - tts_internal
```

And declare:

```yaml
networks:
  edge:
    external: true

  ollama_internal:
    external: true

  tts_internal:
    external: true
```

Open WebUI should therefore be connected to:

```text
edge
ollama_internal
tts_internal
```

Ollama remains connected ONLY to:

```text
ollama_internal
```

The TTS server remains connected ONLY to:

```text
tts_internal
```

---

# Step 6 — Configure Open WebUI

Configure Open WebUI to use the local TTS server.

Prefer Open WebUI's native OpenAI-compatible TTS integration rather than custom application code.

The configured URL should use the Docker service name rather than localhost.

For example:

```text
http://kokoro:<port>/v1
```

Do NOT configure:

```text
http://localhost:<port>
```

Inside the Open WebUI container, `localhost` refers to the Open WebUI container itself.

---

# Step 7 — Connectivity Test

From inside Open WebUI, verify DNS/network connectivity.

Example:

```bash
docker exec open-webui curl -v http://kokoro:<port>/
```

Then test the appropriate health/model/API endpoint documented by the selected TTS server.

The test must originate from `open-webui`, because that represents the actual production network path.

---

# Step 8 — Audio Generation Test

Test the OpenAI-compatible speech endpoint directly before configuring the UI.

Conceptually:

```bash
curl http://kokoro:<port>/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{
    "model": "<verified-model>",
    "voice": "<verified-voice>",
    "input": "The Roman Empire was one of the most influential civilizations in history."
  }'
```

Use the actual API contract documented by the selected server.

Do not assume the model or voice names above.

Verify that valid audio is returned before troubleshooting Open WebUI.

---

# Step 9 — History Tutor

Once TTS works, create a History Tutor model/preset in Open WebUI using `qwen3:32b`.

Suggested system prompt:

```text
You are a history tutor for a student.

When asked for a history fact, explain one interesting historical
event, person, invention, civilization, or discovery.

Keep spoken responses approximately 45–90 seconds.

Use an engaging storytelling style while prioritizing historical
accuracy.

Explain unfamiliar terms rather than assuming the listener already
knows them.

When appropriate, explain:

- what happened
- when it happened
- why it mattered
- one surprising or memorable detail

Distinguish established historical facts from uncertain, disputed,
legendary, or speculative claims.

Write naturally for spoken audio rather than like a textbook.
```

Example request:

```text
Tell me an interesting fact about ancient Rome.
```

Flow:

```text
Student
   ↓
Open WebUI
   ↓
qwen3:32b
   ↓
History response
   ↓
Open WebUI TTS
   ↓
Kokoro
   ↓
Audio playback
```

---

# Future Enhancement — Generated History Library

Do NOT implement this until interactive TTS works reliably.

A later phase can automatically generate audio files:

```text
Qwen
  ↓
History script
  ↓
TTS
  ↓
MP3/WAV
  ↓
Media library
```

Possible destination:

```text
/srv/media/audio/History
```

Example:

```text
History/
├── Ancient Egypt/
├── Ancient Greece/
├── Roman Empire/
├── Middle Ages/
├── American Revolution/
├── Industrial Revolution/
└── World War II/
```

This library could later be indexed by Jellyfin.

---

# Security Requirements

Do NOT expose Ollama directly.

Do NOT expose the TTS API directly.

Do NOT add Ollama to `edge`.

Do NOT add the TTS container to `edge`.

Do NOT publish unnecessary Docker ports.

Expected network boundaries:

```text
Caddy
  |
 edge
  |
Open WebUI
 /       \
ollama    tts
private   private
```

Only Open WebUI should bridge these networks.

---

# GPU Considerations

Host GPU:

```text
NVIDIA RTX 5090
32 GB VRAM
```

Primary Ollama model:

```text
qwen3:32b
Q4_K_M
```

Qwen may consume approximately 20–30 GB of VRAM depending on context and runtime configuration.

Do not configure the TTS service to consume large amounts of VRAM without checking contention.

Monitor:

```bash
nvidia-smi
```

And:

```bash
docker exec ollama ollama ps
```

`qwen3:32b` should remain:

```text
100% GPU
```

Avoid a TTS configuration that causes Qwen to spill layers to CPU.

---

# Validation Checklist

After implementation verify:

```text
[ ] tts_internal Docker network exists
[ ] TTS container is running
[ ] TTS container is NOT on edge
[ ] TTS container has no unnecessary published host ports
[ ] Open WebUI is connected to tts_internal
[ ] Open WebUI can resolve the TTS container by service/container name
[ ] Open WebUI can reach the TTS API
[ ] /v1/audio/speech successfully produces audio
[ ] Open WebUI can play generated speech
[ ] qwen3:32b remains 100% GPU
[ ] ai.example.com continues to require Open WebUI authentication
[ ] Ollama remains inaccessible directly from the Internet
```

---

# Existing Commands

Ollama:

```bash
docker exec ollama ollama list
docker exec ollama ollama ps
docker exec ollama nvidia-smi
```

Open WebUI:

```bash
cd /srv/apps/open-webui
docker compose logs -f
```

Networks:

```bash
docker network inspect edge
docker network inspect ollama_internal
docker network inspect tts_internal
```

Update Open WebUI:

```bash
cd /srv/apps/open-webui
docker compose pull
docker compose up -d
```

Gateway:

```bash
cd /srv/apps/gateway

docker compose exec caddy caddy validate \
  --config /etc/caddy/Caddyfile

docker compose restart
```

---

# Implementation Principle

Keep the responsibilities separate:

```text
Qwen = reasoning and content generation

Open WebUI = user interface and orchestration

Kokoro/TTS = speech generation

Caddy = public HTTPS gateway

Docker networks = service isolation
```

Do not modify the existing Ollama exposure model merely to support TTS.

Get interactive Open WebUI TTS working first.

Only after that is stable should automated MP3 generation or Jellyfin integration be implemented.


# Change of requirements: 

The primary objective is not interactive TTS in Open WebUI. Build a batch content-generation pipeline that uses the existing qwen3:32b Ollama model to generate historically accurate short segments, Kokoro to synthesize each segment to audio, and FFmpeg to combine the resulting audio/visual segments into a single approximately 60-minute MP4 video. Keep individual scripts and audio clips so failed segments can be regenerated without rebuilding the entire episode. Kokoro should initially run on CPU to avoid RTX 5090/Blackwell compatibility problems and VRAM contention with Qwen. Design the pipeline so GPU TTS can be enabled later without changing the rest of the architecture.

Build the next phase of my local AI history-video system.

IMPORTANT:
The existing infrastructure is working. Do not redesign, replace, expose,
or unnecessarily modify Ollama, Open WebUI, Kokoro, Caddy, or their Docker
networks.

CURRENT WORKING SERVICES

Ollama:
  container: ollama
  API: http://ollama:11434
  model: qwen3:32b
  network: ollama_internal
  GPU: RTX 5090

Kokoro:
  container: kokoro
  image: ghcr.io/remsky/kokoro-fastapi-cpu:v0.9.0
  API: http://kokoro:8880
  network: tts_internal
  voice: af_heart

The following Kokoro endpoint has already been tested successfully:

POST http://kokoro:8880/v1/audio/speech

with:

{
  "model": "kokoro",
  "voice": "af_heart",
  "response_format": "mp3"
}

Open WebUI is connected to both ollama_internal and tts_internal.

OBJECTIVE

Create a new application:

/srv/apps/history-generator

It must generate approximately one-hour educational history programs
from a single topic.

Eventually I want to be able to run:

./generate.sh "Ancient Rome"

or:

./generate.sh "The American Revolution"

and receive a finished MP4.

ARCHITECTURE

Topic
  |
  v
qwen3:32b
  |
  v
Episode outline
  |
  v
Individual history segments
  |
  v
Kokoro TTS
  |
  v
Individual audio files
  |
  v
Measure actual audio durations
  |
  v
FFmpeg
  |
  v
Approximately 60-minute MP4


DO NOT ask Qwen to generate an entire one-hour script in one prompt.

Generate an outline first and then generate individual segments.

Each segment should be independently stored so generation can resume
after failure without starting over.


DIRECTORY STRUCTURE

Use approximately:

/srv/apps/history-generator/
    compose.yaml
    generate.sh
    src/
    output/

Each episode should have:

output/<episode-slug>/
    manifest.json
    outline.json

    scripts/
        001.txt
        002.txt
        ...

    audio/
        001.mp3
        002.mp3
        ...

    video/
        ...

    final/
        <episode-slug>.mp4


MANIFEST

Maintain a manifest similar to:

{
  "title": "Amazing Facts About Ancient Rome",
  "topic": "Ancient Rome",
  "target_duration_seconds": 3600,
  "voice": "af_heart",
  "segments": [
    {
      "number": 1,
      "title": "Roman Concrete",
      "script": "scripts/001.txt",
      "audio": "audio/001.mp3",
      "duration": 63.4,
      "status": "complete"
    }
  ]
}


OLLAMA

The generator container should join:

ollama_internal

Use:

http://ollama:11434

Use:

qwen3:32b

Qwen should generate structured JSON wherever practical.

First ask Qwen for an episode outline containing many distinct,
non-repetitive historical subjects.

Then generate each segment individually.

The narration should:

- be engaging when spoken aloud
- explain unfamiliar terminology
- include dates when relevant
- explain why events mattered
- contain memorable details
- avoid repetitive introductions such as "Did you know?"
- avoid excessive headings or formatting because the output is narration
- distinguish established facts from disputed or uncertain claims
- avoid inventing quotations
- avoid presenting legends as established historical facts

Target approximately 60-90 seconds of narration per segment.


TTS

The generator container should also join:

tts_internal

Use:

http://kokoro:8880/v1/audio/speech

Defaults:

model: kokoro
voice: af_heart
response_format: mp3

Make voice configurable from the command line or environment.

Do NOT expose Kokoro publicly.


DURATION CONTROL

Do not assume:

60 segments = 60 minutes.

After every audio file is generated, use ffprobe to determine its
actual duration.

Record that duration in manifest.json.

Continue generating segments until total narration duration reaches
the configured target.

Default:

TARGET_DURATION=3600

Allow:

./generate.sh --duration 600 "Ancient Rome"

for a 10-minute test episode.

Before attempting a one-hour episode, verify the entire pipeline using
a 5-10 minute episode.


RESUMABILITY

This is important.

Generation may take a long time.

If:

scripts/017.txt

and:

audio/017.mp3

already exist and are valid, do not regenerate them.

The program should be safe to interrupt and restart.

Example:

./generate.sh "Ancient Rome"

should resume an incomplete Ancient Rome episode.

Provide an explicit option such as:

--force

if I intentionally want to regenerate an episode.


RETRIES

Implement retries for both Ollama and Kokoro requests.

A failed segment should not destroy completed work.

Log which segment failed and continue/resume appropriately.


FFMPEG

Install/use ffmpeg and ffprobe inside the generator environment.

For phase 1, keep video generation SIMPLE.

Do not build an elaborate AI image-generation system yet.

Create a clean 1920x1080 video using:

- a dark/simple background
- episode title
- current segment title
- narration audio

The important goal is proving the complete automated pipeline.

Encode the final result as:

H.264 video
AAC audio
1920x1080

Produce a standard MP4 that plays in browsers, VLC, televisions,
Jellyfin, etc.


FUTURE VISUALS

Design the code so a visual-generation stage can later be inserted:

segment
  |
  +-- script
  +-- narration
  +-- images
  +-- video segment

But DO NOT implement image generation yet.

Eventually we may add historical images, maps, AI-generated
illustrations, Ken Burns pan/zoom effects, subtitles and transitions.

Keep this future extension in mind without overengineering phase 1.


LOGGING

While running, show useful progress such as:

Episode: Ancient Rome
Target: 3600 seconds

[01] Roman Concrete
     Generating script...
     Generating narration...
     Duration: 68.2 sec
     Total: 68.2 / 3600

[02] Life in a Roman Legion
     Generating script...
     Generating narration...
     Duration: 74.8 sec
     Total: 143.0 / 3600

etc.


TEST MODE

Before generating an hour, support:

./generate.sh --duration 300 "Ancient Rome"

This should produce an approximately five-minute MP4.

Use this to validate:

Qwen
  ->
Kokoro
  ->
ffprobe
  ->
FFmpeg
  ->
MP4


SECURITY

Do not publish Ollama.

Do not publish Kokoro.

Do not put either service on edge.

The generator should communicate with them exclusively through the
existing private Docker networks.

The history-generator itself does not need to be publicly accessible.


IMPORTANT IMPLEMENTATION RULE

Inspect the existing environment before making changes.

Do not invent API behavior.

Test the actual Ollama and Kokoro endpoints.

Do not modify working infrastructure unless necessary.

Build history-generator as an independent application on top of the
existing services.


WHEN FINISHED

Do not immediately generate a one-hour episode.

First run or give me the exact command for a 5-minute test:

./generate.sh --duration 300 "Ancient Rome"

Then report:

1. Files created
2. Number of segments
3. Total narration duration
4. Final MP4 duration
5. Final MP4 path
6. Any errors/warnings
7. Exact command to generate the full one-hour version

# Adding emotion to the voice
Implement a `pitch_semitones` option in my Docker-based history video generator.

**Current architecture**

* Project: `/srv/apps/history-generator`
* FastAPI service: `history-api`
* Kokoro FastAPI provides narration audio.
* The generator already supports `voice` and `speed` in its job request.
* Narration is generated in segments, then combined into a final video with optional ambient audio.
* The episode manifest and generated files are persisted under `./output`.
* Docker Compose builds the `history-api` image from the local project.

**Goal**

Allow me to adjust the narrator's pitch independently of speaking speed.

**Requirements**

1. Add `pitch_semitones` to the job request, with a default of `0.0`. Support a configurable range of `-4.0` to `+4.0` semitones. Validate that the value is finite and within range.

2. Continue passing `voice` and `speed` to Kokoro as currently implemented. Do not pass `pitch_semitones` to Kokoro.

3. After Kokoro generates each narration audio segment, apply pitch shifting with FFmpeg's `rubberband` audio filter. Preserve the segment's duration and speaking speed.

4. Convert semitones to the pitch multiplier using:

   `pitch_factor = 2 ** (pitch_semitones / 12)`

   Use the filter `rubberband=pitch=<pitch_factor>:tempo=1.0`.

5. Apply pitch processing **only to narration**, before video segment creation and before mixing ambient audio. Do not pitch-shift ambient audio, music, or the completed MP4.

6. When `pitch_semitones` is `0`, skip pitch processing entirely to avoid unnecessary re-encoding.

7. Preserve the original Kokoro audio and write pitch-adjusted narration to a separate file. Use the adjusted file for subsequent video generation.

8. Include `pitch_semitones` in the job response and episode manifest. Ensure a change in pitch invalidates the appropriate cached narration/video outputs without requiring Kokoro to regenerate the original speech.

9. Preserve existing episodes and their original behavior when `pitch_semitones` is omitted.

10. Check that FFmpeg supports `rubberband` and return a clear error if the filter is unavailable. Do not silently generate an unadjusted video when a nonzero pitch was requested.

11. Add tests for zero pitch, positive and negative pitch, validation, cached-output invalidation, and preservation of audio duration.

12. Inspect the existing code and file structure before making changes. Do not rewrite unrelated parts of the pipeline.

**Acceptance test**

Generate three short samples with the same text, voice, and speed, using pitch values `-2`, `0`, and `+2`. All three should have approximately the same duration, with audibly different pitches. Confirm that the ambient audio remains unchanged.

# Add backgournd music
# AGENTS.md — Background Music Integration

## Project context

Project root: `/srv/apps/history-generator`

This project generates educational history and science videos using:

* Ollama/Qwen for scripts and episode planning.
* Kokoro FastAPI for narration.
* FFmpeg for audio processing, video generation, and final rendering.
* A Dockerized `history-api` service and a command-line generator.
* Persistent episode manifests and generated assets under `output/`.

The generator already supports:

* Narrator voice and speaking speed.
* Narrator pitch adjustment via `pitch_semitones` and FFmpeg's `rubberband` filter.
* Procedurally generated ambient audio.
* Segment-based generation and resumable processing.
* API, CLI, and Open WebUI tool interfaces.

**Do not replace or break any of these existing capabilities.**

The user has downloaded background music to the RTX server. The host music library is:

`/srv/media/audio/music/`

It currently includes:

`/srv/media/audio/music/sleep-ambient/`

The existing sound-effects library is separate:

`/srv/media/audio/effects/`

The Jellyfin container mounts `/srv/media` to `/media`, but Jellyfin is not part of the video-generation pipeline.

## Objective

Implement optional background music for generated episodes.

The generator should select an appropriate local music track, adjust it to a consistent listening level, extend it to cover the episode, and mix it underneath Kokoro narration.

The initial use case is relaxing, sleep-oriented educational videos. The soundtrack should be continuous, unobtrusive, and free of abrupt starts, stops, or volume spikes.

All music processing must happen locally. Do not introduce a dependency on Pixabay, Jellyfin, Freesound, or another external service at video-generation time.

## 1. Inspect the existing implementation first

Before making changes, inspect:

* `src/main.py`
* `src/api.py`
* `src/pipeline.py`
* `src/video.py`
* `src/ambient.py`
* `src/pitch.py`
* `generate.sh`
* Docker Compose configuration
* Existing tests and episode manifests
* `open-webui/tools/history_generator_tool.py`, or the actual tool file in the repository

Determine how the current pipeline builds narration segments, assembles the final video, generates procedural ambient audio, mixes audio, and resumes completed jobs.

Reuse the existing architecture and helpers wherever possible.

Do not assume filenames, function signatures, manifest keys, or Docker mount paths beyond what is confirmed in the repository.

## 2. Music library access

Mount the host music library read-only into the generator container:

Host: `/srv/media/audio/music`

Container: `/app/audio-library/music`

Preserve all existing Docker mounts and volumes.

Make the container music-library path configurable using an environment variable such as:

`MUSIC_LIBRARY_DIR=/app/audio-library/music`

The generator must work when the library is empty or unavailable if background music is disabled.

When music is explicitly enabled and no suitable files exist, return a clear error rather than silently omitting the requested soundtrack.

Do not modify, rename, delete, or overwrite the source music files.

## 3. Music catalog

Implement a local catalog that describes available music tracks.

Use an existing catalog if the repository already has a suitable implementation. Otherwise, introduce a simple `catalog.json` in the music library.

Suggested entry:

```json
{
  "id": "sleep-ambient-001",
  "title": "Quiet Ocean",
  "file": "sleep-ambient/quiet-ocean.mp3",
  "category": "sleep-ambient",
  "tags": ["sleep", "ocean", "calm", "instrumental"],
  "mood": "peaceful",
  "energy": "very-low",
  "vocals": false,
  "percussion": false,
  "sleep_safe": true,
  "creator": "Artist name",
  "source_url": "https://example.com/track-page",
  "license": "License recorded at download",
  "duration_seconds": 240
}
```

The example is a schema illustration, not a real music track.

Provide a command to scan the local library and generate or update the catalog.

The scanner should:

* Discover supported audio formats, including MP3, WAV, FLAC, OGG, and M4A.
* Use `ffprobe` to obtain duration and audio-stream information.
* Generate stable IDs.
* Preserve existing user-edited metadata when rescanning.
* Avoid duplicate entries.
* Use folder names as initial category hints.
* Mark newly discovered tracks as `sleep_safe: false` or unreviewed until explicitly approved.
* Never infer a track's license or claim that it is copyright-free based on its filename or folder.

Do not automatically download music or scrape music websites.

## 4. New generation parameters

Add optional background-music parameters to the API request model, CLI, and Open WebUI tool.

Suggested interface:

```json
{
  "music": true,
  "music_mood": "sleep-ambient",
  "music_track_id": null,
  "music_level_db": -25,
  "music_fade_in_seconds": 8,
  "music_fade_out_seconds": 20
}
```

These are proposed parameters; adapt naming to the project's existing conventions.

Requirements:

* `music`: Boolean, default `false` to preserve existing behavior.
* `music_mood`: Optional category or mood used for automatic track selection.
* `music_track_id`: Optional exact track selection. When supplied, it overrides automatic selection.
* `music_level_db`: A configurable music level with sensible validation.
* Fade-in and fade-out durations: Nonnegative, validated, and capped to the actual soundtrack duration.

Preserve the existing `--ambient` and `--no-ambient` flags.

Add `--music` and `--no-music` CLI flags, along with options for music mood, exact track, level, and fades.

Document how music and procedural ambient audio interact.

## 5. Track selection

For the first implementation, use deterministic selection from the local catalog.

If an exact track ID is requested, select that track and validate that the file exists and is readable.

Otherwise, filter by the requested category or mood and select from approved tracks.

For sleep-oriented videos, prefer tracks marked:

* `sleep_safe: true`
* `vocals: false`
* `percussion: false`
* `energy: very-low` or `low`

Do not assume a track is suitable for sleep merely because it is in the `sleep-ambient` folder.

If there are multiple suitable tracks, choose deterministically using the episode ID or another stable seed. Record the selected track ID in the episode manifest so rerunning the episode does not unexpectedly select different music.

Do not let Qwen invent filenames or absolute paths. If Qwen proposes a music mood, resolve that mood against the actual catalog.

Validate all resolved paths to ensure they remain inside the configured music-library directory.

## 6. Audio processing and mixing

Implement music processing as a distinct stage in the existing pipeline.

Recommended order:

1. Generate raw Kokoro narration.
2. Apply narrator pitch adjustment when requested.
3. Build and assemble narration/video segments.
4. Generate or load the existing procedural ambient bed when enabled.
5. Prepare the selected background music.
6. Mix narration, music, and optional procedural ambient into the final video.

Keep the source music unchanged.

The prepared music should:

* Match the final episode's actual duration, not merely the requested target duration.
* Loop seamlessly or use suitable crossfades when the source track is shorter than the episode.
* Trim excess audio when the source is longer.
* Apply configurable fade-in and fade-out.
* Avoid clicks or abrupt transitions.
* Use a consistent sample rate and channel layout for mixing.

Use FFmpeg for processing.

**Music level must be based on measured or normalized audio, not only a fixed gain applied to arbitrary source files.**

Implement a reasonable loudness-management strategy using FFmpeg, such as measuring the source with `loudnorm` and applying a controlled normalization or gain stage.

Keep the narration clearly intelligible. Add peak limiting or another appropriate safeguard to prevent clipping in the final mix.

For the initial implementation, a fixed low music level is acceptable if it is measured and validated. Dynamic ducking beneath speech can be a later enhancement.

Do not apply narrator pitch shifting to music or sound effects.

Do not apply music processing to the original Kokoro narration files.

## 7. Music and procedural ambient audio

The generator must support all four combinations:

| Music | Procedural ambient | Expected result                      |
| ----- | ------------------ | ------------------------------------ |
| Off   | Off                | Narration only                       |
| On    | Off                | Narration + music                    |
| Off   | On                 | Narration + existing ambient         |
| On    | On                 | Narration + music + existing ambient |

When both music and procedural ambient are enabled, prevent the combined background layers from overwhelming the narrator.

Preserve the existing ambient implementation, including its current caching and volume behavior, unless a change is necessary for correct mixing.

Do not mix background music separately into every narration segment if that would create audible restarts at segment boundaries. Prefer one continuous music bed mixed at final assembly.

## 8. Resumability and cache invalidation

Preserve the generator's existing resumability behavior.

Changing music settings must not regenerate:

* The script.
* Kokoro narration.
* Pitch-adjusted narration.
* Narration segment videos.

Instead, invalidate only the prepared music and downstream final-mix outputs that depend on the changed settings.

Changing narrator pitch should retain the existing pitch-processing invalidation behavior and rebuild the final mix as needed.

Store the following in the episode manifest:

* Whether music is enabled.
* Requested music mood.
* Selected track ID and relative file path.
* Source track identity or fingerprint.
* Music level and fade settings.
* Prepared music path.
* Final-mix settings and output path.

Ensure the cache detects when a selected music file has changed, even if its filename remains the same.

If music is disabled after previously being enabled, regenerate the final output without music and avoid accidentally reusing the old soundtrack.

Do not overwrite an existing finished episode with a partially rendered or failed output. Use temporary files and atomic replacement where appropriate.

## 9. API and status reporting

Include music settings and selected-track information in the API response, job status, and episode manifest.

Expose clear errors for:

* Missing music library.
* Unknown track ID.
* No suitable approved tracks.
* Missing or unreadable source file.
* Invalid music parameters.
* FFmpeg probing, decoding, or mixing failure.

Do not report a successful music-enabled render if the final video lacks the requested music.

## 10. Tests

Add automated tests for:

* Catalog discovery and metadata preservation.
* Track selection and deterministic reuse.
* Invalid and unsafe file paths.
* Empty music library.
* Music enabled and disabled.
* All four music/ambient combinations.
* Short-track looping and long-track trimming.
* Fade durations.
* Music-level validation and clipping prevention.
* Cache invalidation when changing tracks, levels, fades, or enabling/disabling music.
* Cache reuse of unchanged Kokoro narration and pitch-adjusted narration.
* Existing episode behavior when music parameters are omitted.

Include an integration test using generated synthetic audio so it does not require live Kokoro or copyrighted music.

Verify that the final mixed audio has the expected duration and contains both the narration and music signals.

Run the existing test suite and report regressions.

## 11. Live acceptance test

Use an existing completed episode and one locally approved ambient music track.

Render these versions without regenerating the script or Kokoro narration:

1. Narration only.
2. Narration with background music.
3. Narration with background music and procedural ambient.

Confirm:

* Narration remains intelligible.
* Music plays continuously across narration segment boundaries.
* No sudden loud transitions occur.
* The music fades smoothly at the beginning and end.
* The final video duration is correct.
* Changing the music settings does not trigger unnecessary Kokoro calls.
* The original downloaded music file remains unchanged.

Do not run a full hour-long generation merely to validate the implementation. Use a short existing episode or a short synthetic integration test.

## 12. Deliverables

Provide:

* The implemented code changes.
* Any required Docker Compose changes.
* A local music-library catalog/scanner command.
* Updated CLI, API, and Open WebUI tool parameters.
* Updated documentation in `docs/HISTORY-GENERATOR.md`.
* Automated test results.
* Exact commands to generate a short music-enabled test episode.
* A concise explanation of any limitations or remaining work.

**Before making changes, inspect the repository and existing episode format. Implement the smallest coherent change that integrates with the current pipeline. Do not rewrite unrelated components or regenerate existing media unnecessarily.**

# Add sentence gap
## Improve narration pacing and duration control

The inter-segment gap feature is implemented, but it does not address the pacing issue I hear in the narration.

My latest 60-second episode, **“Sea Creatures: Life in the Deep Ocean,”** completed only **1 of 3 outlined segments**. That segment’s narration was **90.8 seconds at Kokoro speed 0.85**. As a result, changing `--segment-gap` from 1.5 to 5 seconds had no audible effect: there were no transitions between completed segments.

Please inspect the existing pipeline and implement the following changes.

### 1. Add configurable pauses between sentences

Introduce `--sentence-gap <seconds>`, defaulting to **0.5 seconds**, with a reasonable validated range such as 0–2 seconds.

Apply it **within each narration segment**, independently of `--segment-gap`. Preserve the existing inter-segment gap behavior.

Inspect how Kokoro handles punctuation and sentence boundaries before choosing an implementation. If synthesizing sentences separately is necessary, preserve natural intonation as much as possible. Do not split on abbreviations, decimal numbers, or other punctuation that does not end a sentence. Avoid inserting pauses where the narration already contains a sufficiently long natural pause.

The goal is relaxed, natural narration—not a mechanical pause after every punctuation mark.

### 2. Make the episode duration target meaningful

Investigate why a 60-second target generated a first segment lasting 90.8 seconds and stopped with only 1 of 3 segments completed.

Account for the selected voice speed, sentence gaps, and inter-segment gaps when budgeting script length and total runtime. Prefer generating appropriately sized scripts rather than truncating speech or accelerating the finished audio.

If the requested duration cannot accommodate the outlined segments, adjust the outline or script allocation before synthesis. Report the estimated duration and actual duration clearly.

### 3. Handle caching and resumed episodes correctly

Changing `--sentence-gap` must invalidate and rebuild the affected narration audio and downstream segment/final videos, without unnecessarily regenerating the scripts.

Changing only `--segment-gap` should rebuild the final video as needed without re-synthesizing narration.

Do not require `--force` for either change, since it deletes the existing episode directory.

Ensure background music continues through both sentence and segment pauses. Account for all added pauses in audio/video duration calculations.

### 4. Expose and test the feature

Thread `sentence_gap_seconds` through the CLI, API, Open WebUI tool, manifest, and documentation, following the pattern used for `segment_gap_seconds`.

Add tests for sentence-boundary handling, duration calculations, cache invalidation, zero-gap behavior, and audible music during pauses.

Make the run summary report the number of completed segments and the number of inter-segment gaps inserted, so a single-segment episode clearly reports **0 inter-segment gaps**.

### Acceptance test

Generate a fresh 60-second “Sea Creatures: Life in the Deep Ocean” episode using:

* Voice: `bm_atten_inno`
* Speed: `0.85`
* Pitch: `0`
* Sentence gap: `0.5` seconds
* Segment gap: `1.5` seconds
* Sleep-ambient background music at `-12`
* No procedural ambient bed

Compare it with a `--sentence-gap 0` render using the same script and voice. Confirm that sentence pacing changes audibly, music continues through the pauses, and the finished duration is reasonably close to the requested 60 seconds.

Run the full test suite and report the results. Do not delete existing episode assets or overwrite the current final MP4 without preserving a copy for comparison.

# Adding visualizations

## Add animated mathematics backgrounds to the History Generator

I want to add an optional animated mathematics background to the existing video-generation pipeline.

The background should feature smoothly animated mathematical functions, such as sine and cosine waves, Fourier-series approximations, Lissajous curves, parametric equations, and other visually interesting mathematical patterns.

The goal is a calm, visually engaging background that can loop throughout an episode without distracting from the narration.

### 1. Add a configurable mathematics background

Introduce a CLI option such as:

`--visual-style math`

Also expose the setting through the API and Open WebUI History Generator tool.

Preserve the existing visual-generation behavior as the default. Mathematics backgrounds should be opt-in.

### 2. Random selection with consistency per episode

When generating a new episode, randomly select a mathematical visualization and its parameters.

For example, one episode might use animated sine and cosine waves, while another uses a Fourier-series approximation or a Lissajous curve.

Once selected, store the visualization type, parameters, colors, and random seed in the episode manifest.

**Every segment within the same episode must use the same visual theme and animation configuration.** Resuming or rebuilding an episode must reproduce the same background unless I explicitly request a new one.

Do not select a new random function for each segment.

### 3. Create a seamless looping animation

Generate a short, reusable animation loop, approximately 15–30 seconds long, that can repeat for the entire episode.

The animation should:

* Loop seamlessly without visible jumps or resets.
* Use smooth, continuous movement rather than rapid transitions.
* Display mathematically meaningful curves, not arbitrary shapes labeled as equations.
* Have a restrained visual style suitable for relaxed narration.
* Use a consistent resolution, frame rate, and aspect ratio compatible with the existing video pipeline.

Consider animating the phase of sine/cosine waves, Fourier-series harmonics, or the position of a point tracing a parametric curve.

Choose animation parameters that return to their starting state at the end of the loop.

### 4. Integrate with the existing video pipeline

Inspect the current FFmpeg rendering pipeline and determine the most efficient way to generate and reuse the animation.

Prefer generating one background asset per episode and looping it during video rendering rather than independently rendering an entire animation for every segment.

The background must cover the complete video duration, including sentence gaps and inter-segment gaps.

Preserve the existing narration, music, subtitles, and other visual elements where applicable. The mathematical animation must not obscure readable text.

Do not add unnecessary GPU dependencies or require an external video-generation service. Prefer the existing Python and FFmpeg stack where practical.

### 5. Support future mathematical visualizations

Design the implementation so additional functions can be added without rewriting the video pipeline.

Start with a small set of polished visualizations:

* Animated sine and cosine waves.
* Fourier-series approximation of a square or sawtooth wave.
* Lissajous curves.
* Animated parametric curves or harmonic motion.

For Fourier-series visualizations, ensure the mathematics is correct and the animation remains smooth and periodic.

### 6. Add caching, testing, and documentation

Cache the generated background using the selected visualization parameters and seed.

Changing narration speed, sentence gaps, or music should not regenerate the mathematical background unnecessarily.

Changing the mathematical visualization settings should invalidate the relevant video assets without regenerating narration or scripts.

Add tests for deterministic selection, manifest persistence, seamless looping, duration coverage, cache invalidation, and compatibility with existing video-generation modes.

Document the new CLI, API, and Open WebUI options.

### Acceptance test

Generate two short episodes with `--visual-style math`.

Verify that each episode can select a different mathematical visualization, but that all segments within a given episode use the same animation.

Rebuild one episode and confirm that its selected visualization and parameters remain unchanged.

Confirm that the animation loops without a visible jump, covers the entire final video, and does not interfere with narration or background music.

Preserve all existing episodes and their generated assets.


# GUI for history-generator

# Feature Request: History Generator Configuration UI

## Objective

Build a graphical configuration interface for the History Generator so I can configure and start video-generation jobs without having to specify every parameter in an Ollama chat prompt.

The History Generator is already integrated with Ollama through an Open WebUI tool. **Preserve that integration.** The new interface should provide an additional way to configure and submit jobs, not replace the existing conversational workflow.

Both the graphical interface and the Ollama tool must use the same History Generator API.

## 1. Investigate the existing architecture

Before implementing anything, inspect:

* The current History Generator API and its supported configuration parameters.
* The existing Open WebUI History Generator tool.
* The Open WebUI deployment, version, and available extension mechanisms.
* The current Docker networking and authentication configuration.
* The existing job-status and ntfy notification integrations.

Determine the most maintainable way to provide a graphical configuration interface.

Prefer an interface accessible from the existing Open WebUI environment. Investigate supported Open WebUI extension mechanisms before modifying Open WebUI's source code or creating a separate application.

If a native Open WebUI integration cannot provide the required functionality cleanly, propose a small standalone configuration page backed by the existing History Generator API.

Do not create a second video-generation pipeline.

## 2. Video-generation configuration form

Create a form that exposes all supported History Generator parameters.

At minimum, include:

| Setting                  | Control                               | Default              |
| ------------------------ | ------------------------------------- | -------------------- |
| Episode topic            | Text input                            | Required             |
| Target duration          | Numeric input or preset selector      | Existing API default |
| Narration voice          | Dropdown of supported Kokoro voices   | `bm_atten_inno`      |
| Speaking speed           | Numeric input or slider               | `0.85`               |
| Pitch                    | Numeric input or slider               | `0`                  |
| Sentence gap             | Slider or numeric input, 0–2 seconds  | `0.5`                |
| Segment gap              | Slider or numeric input, 0–10 seconds | `1.5`                |
| Background music         | Toggle                                | Existing API default |
| Music mood               | Dropdown of supported moods           | `sleep-ambient`      |
| Music level              | Numeric input or slider               | `-12`                |
| Procedural ambient sound | Toggle                                | Disabled             |

Inspect the API for additional supported parameters and expose them where appropriate.

Do not assume the table above is the complete API schema. Use the actual supported values and validation rules from the existing implementation.

### Mathematics visualizations

A separate agent is currently implementing animated mathematics backgrounds.

Do not interfere with that work or implement a competing visualization system.

Design the form so that the new visual settings can be added once the mathematics visualization feature is available and its API contract is finalized.

Do not expose unfinished options that the running API cannot accept.

## 3. User experience

The interface should allow me to:

1. Enter a video topic.
2. Adjust the generation parameters.
3. Review the configuration before submitting.
4. Start a generation job.
5. See the returned job ID and current status.
6. Check progress, including completed segments and estimated or actual duration.
7. See the final host filesystem path when generation finishes.

Display useful validation errors before submission and clear API errors if a request fails.

Do not block the interface while a video is generating. Use the existing asynchronous job API and status endpoint.

The interface should work on both desktop and mobile browsers.

## 4. Configuration presets

Add support for reusable configuration presets.

Start with a preset named **Relaxed Documentary**:

* Voice: `bm_atten_inno`
* Speed: `0.85`
* Pitch: `0`
* Sentence gap: `0.5` seconds
* Segment gap: `1.5` seconds
* Background music: enabled
* Music mood: `sleep-ambient`
* Music level: `-12`
* Procedural ambient sound: disabled

Allow me to modify a preset before submitting a job.

If practical within the chosen interface architecture, support saving and reusing custom presets. Presets should store generation settings, not API credentials.

## 5. API and authentication

The graphical interface must use the existing History Generator API as the single source of truth.

Do not duplicate the generation logic or maintain a separate set of parameter-validation rules.

Keep `history-api` private. Do not expose it publicly simply to make the configuration form work.

If the UI requires a server-side proxy to reach the private API, implement it using the existing authenticated infrastructure.

Do not expose API credentials, internal service tokens, or privileged Docker-network addresses in browser-side JavaScript.

Preserve the existing Open WebUI authentication and access controls where the chosen architecture supports them.

## 6. Output and notifications

The generator should continue saving completed MP4 files to its existing output directory.

The UI only needs to display the final host filesystem path and job status.

Preserve the existing ntfy completion notification.

Do not upload completed videos into Open WebUI, duplicate them in another storage system, create public video URLs, or introduce a new video-serving service.

## 7. Preserve Ollama integration

The existing Ollama/Open WebUI History Generator tool must continue to work.

I should be able to generate a video either by:

* Asking Ollama to generate one through the existing chat tool.
* Opening the graphical configuration interface and submitting a job directly.

Both workflows must submit jobs to the same API and produce the same output format.

Avoid changing the existing model configuration, tool permissions, or unrelated Open WebUI settings.

## 8. Testing and documentation

Add appropriate tests for:

* Parameter validation and default values.
* Correct API request construction.
* Preset selection and parameter overrides.
* Job submission and progress reporting.
* Failed API requests and invalid configuration values.
* Compatibility with the existing Ollama tool.

Perform an end-to-end test using a short episode with a unique title. Confirm that the UI submits the selected parameters, the job completes, ntfy still sends its notification, and the final MP4 is saved to the expected host directory.

Document how to access the interface, configure an episode, manage presets, and deploy future UI updates.

## Implementation constraints

Preserve all existing episodes, manifests, generated media, API functionality, and Open WebUI configuration.

Do not introduce a new public endpoint or additional video storage.

Do not modify the mathematics visualization implementation while the other agent is working on it.

Before making significant architectural changes, inspect the existing environment and explain the proposed integration approach.

**Deliverable:** A working graphical History Generator configuration interface that complements the existing Ollama chat tool and submits jobs through the existing private History Generator API.
