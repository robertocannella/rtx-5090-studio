# Ollama + Open WebUI (Local AI Stack)

## Purpose

Ollama serves large language models locally on the RTX 5090. Open WebUI provides the browser chat interface in front of it, and Kokoro provides local text-to-speech so responses can be played back as audio.

Public URL:

```text
https://ai.example.com
```

## Architecture

```text
                         Internet
                            |
                 ai.example.com
                            |
                      Caddy gateway :443
                            |
                          edge
                            |
                       open-webui :8080
                       /              \
                      /                \
       ollama_internal                  tts_internal
        (private, not on edge)           (private, not on edge)
               |                                |
            ollama :11434                    kokoro :8880
               |
          qwen3:32b
               |
          RTX 5090
```

Ollama and Kokoro are **not** on the shared `edge` network. Neither has authentication of its own, so each only joins a private network shared with Open WebUI (`ollama_internal` and `tts_internal` respectively). Only Open WebUI is reachable from Caddy/`edge`, and Open WebUI is the only container that bridges to either backend. None of the three containers publish a host port.

Kokoro (Kokoro-FastAPI) runs the CPU image, not GPU: the pre-built GPU image does not yet officially support Blackwell (RTX 5090, `sm_120`) — see [upstream issue #365](https://github.com/remsky/Kokoro-FastAPI/issues/365). Kokoro-82M is small enough that CPU synthesis is fast for short spoken responses, and this keeps VRAM fully reserved for `qwen3:32b`.

## Files

Application directories:

```text
/srv/apps/ollama
/srv/apps/open-webui
/srv/apps/kokoro
```

Persistent data (named Docker volumes, not bind mounts — avoids UID/permission mismatches between the host and the containers' internal users):

```text
ollama_ollama_data           -> /root/.ollama inside the ollama container (models, config)
open-webui_open_webui_data   -> /app/backend/data inside open-webui (users, chats, settings)
```

Kokoro has no persistent volume — it ships its model weights and voices baked into the image.

Inspect actual on-disk location if needed:

```bash
docker volume inspect ollama_ollama_data
docker volume inspect open-webui_open_webui_data
```

## Docker Compose

`/srv/apps/ollama/compose.yaml`:

```yaml
services:
  ollama:
    image: ollama/ollama:latest
    container_name: ollama
    restart: unless-stopped

    volumes:
      - ollama_data:/root/.ollama

    networks:
      - ollama_internal

    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]

volumes:
  ollama_data:

networks:
  ollama_internal:
    external: true
```

`/srv/apps/open-webui/compose.yaml`:

```yaml
services:
  open-webui:
    image: ghcr.io/open-webui/open-webui:main
    container_name: open-webui
    restart: unless-stopped

    environment:
      - OLLAMA_BASE_URL=http://ollama:11434
      - ENABLE_SIGNUP=false
      - AUDIO_TTS_ENGINE=openai
      - AUDIO_TTS_OPENAI_API_BASE_URL=http://kokoro:8880/v1
      - AUDIO_TTS_OPENAI_API_KEY=not-needed
      - AUDIO_TTS_MODEL=kokoro
      - AUDIO_TTS_VOICE=af_bella

    volumes:
      - open_webui_data:/app/backend/data

    networks:
      - edge
      - ollama_internal
      - tts_internal

volumes:
  open_webui_data:

networks:
  edge:
    external: true
  ollama_internal:
    external: true
  tts_internal:
    external: true
```

`/srv/apps/kokoro/compose.yaml`:

```yaml
services:
  kokoro:
    image: ghcr.io/remsky/kokoro-fastapi-cpu:v0.9.0
    container_name: kokoro
    restart: unless-stopped

    networks:
      - tts_internal

networks:
  tts_internal:
    external: true
```

The `AUDIO_TTS_*` environment variables only seed Open WebUI's config the first time that config key is created in its database — on an existing instance they won't override a value already stored there. If TTS settings ever need to change on a running instance, edit them in **Settings → Admin → Audio** in the UI (preferred), or update the `audio.tts.*` rows directly in `open_webui_data`'s `webui.db` `config` table and recreate the container.

The `ollama_internal` and `tts_internal` networks are each created once, outside of any compose project, so multiple projects can reference them as `external`:

```bash
docker network create ollama_internal
docker network create tts_internal
```

Start or update any of the three services from its own directory:

```bash
cd /srv/apps/ollama && docker compose up -d
cd /srv/apps/open-webui && docker compose up -d
cd /srv/apps/kokoro && docker compose up -d
```

## Gateway Route

```caddy
ai.example.com {
    reverse_proxy open-webui:8080
}
```

Unlike `docs.example.com`, this route has **no Caddy Basic Auth**. Auth is Open WebUI's own account login only (same pattern as Jellyfin). This was a deliberate choice after Caddy Basic Auth caused a persistent re-prompt loop in the browser for this route; rather than keep debugging a second auth layer, it was dropped in favor of relying solely on Open WebUI's login.

Validate and restart after any Caddyfile edit:

```bash
cd /srv/apps/gateway
docker compose exec caddy caddy validate --config /etc/caddy/Caddyfile
docker compose restart
```

The first account ever created through Open WebUI's signup page becomes the admin. Once that account exists, public signup is disabled:

```yaml
# open-webui's environment in compose.yaml
- ENABLE_SIGNUP=false
```

Confirm it's active:

```bash
docker exec open-webui curl -s http://localhost:8080/api/config | grep enable_signup
# should show "enable_signup":false
```

If you ever need to add another user, temporarily set `ENABLE_SIGNUP=true`, recreate the container, have them sign up, then set it back to `false` and recreate again — or add them directly from the admin panel inside Open WebUI instead.

## GPU Usage

Ollama requests all GPUs via the same `deploy.resources.reservations.devices` pattern Jellyfin uses. `NVIDIA_VISIBLE_DEVICES`/`NVIDIA_DRIVER_CAPABILITIES` are injected automatically by the host's `nvidia-container-toolkit` — no explicit environment variables were needed.

Verify the GPU is visible in the container:

```bash
docker exec ollama nvidia-smi
```

Verify a model is actually running on GPU (not spilled to CPU):

```bash
docker exec ollama ollama ps
```

`PROCESSOR` should read `100% GPU`. Watch `nvidia-smi` on the host (`memory.used`, `utilization.gpu`) while a prompt is running to confirm VRAM usage and utilization rise.

The GPU is shared with Jellyfin's NVENC/NVDEC transcoding (see `JELLYFIN.md`). Both can use the GPU concurrently; heavy simultaneous transcode + inference will contend for the same 32 GB of VRAM and SM time.

## Models

Current model:

```text
qwen3:32b
```

Dense 32B model, Q4_K_M quantization (~20 GB weights). Chosen because it fits entirely in the RTX 5090's 32 GB of VRAM with headroom for a large context window (loads at ~28 GB resident with a 32K context, confirmed via `ollama ps`), avoiding any CPU offload. Being dense rather than mixture-of-experts also gives more predictable per-token latency for a chat UI than an MoE model of similar quality. Larger dense models (70B-class) don't fit in 32 GB at usable quantization without CPU offload, which would hurt latency; smaller models would leave the 5090 underused.

Common commands:

```bash
docker exec ollama ollama list                 # installed models
docker exec ollama ollama pull <model>          # download/update a model
docker exec ollama ollama rm <model>            # delete a model
docker exec ollama ollama ps                    # currently loaded models + GPU/CPU split
docker exec ollama ollama run <model> "prompt"  # one-off generation from the CLI
```

Be deliberate before pulling additional large models — each 30B+ class model is tens of GB on disk (55 GB free at last check) and only one can be resident in VRAM at full GPU speed at a time.

## Text-to-Speech (Kokoro)

Kokoro-FastAPI (`ghcr.io/remsky/kokoro-fastapi-cpu`) exposes an OpenAI-compatible speech endpoint at `POST /v1/audio/speech`. Open WebUI is configured to use it as its TTS engine, so any chat response can be played back as audio from the UI.

Available voices (72 packs loaded; common English ones):

```text
af_bella, af_heart, af_nicole, af_sarah, af_sky, am_adam, am_michael, bf_emma, bf_isabella, bm_george, bm_lewis
```

List all installed voices:

```bash
docker exec open-webui curl -s http://kokoro:8880/v1/audio/voices
```

Test synthesis directly, bypassing the UI:

```bash
docker exec open-webui curl -s http://kokoro:8880/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{"model": "kokoro", "voice": "af_bella", "input": "Hello from Kokoro."}' \
  -o /tmp/test.mp3
```

A **History Tutor** preset can be created in Open WebUI (Workspace → Models) on top of `qwen3:32b`, with a system prompt geared toward short (45-90 second) spoken history facts, to pair generation with playback.

## Upgrading

```bash
cd /srv/apps/ollama && docker compose pull && docker compose up -d
cd /srv/apps/open-webui && docker compose pull && docker compose up -d
cd /srv/apps/kokoro && docker compose pull && docker compose up -d
```

Update model weights with `ollama pull <model>` (re-pulling the same tag fetches the latest version if the upstream tag was updated).

## Troubleshooting

**GPU not visible inside the container** (`nvidia-smi` fails in `docker exec ollama nvidia-smi`):
- Check the NVIDIA Container Toolkit is installed and configured: `dpkg -l | grep nvidia-container-toolkit`.
- Check `docker info` for the `nvidia` runtime.
- Restart Docker if the toolkit was reinstalled/updated: `sudo systemctl restart docker`, then recreate the container.

**Model running on CPU instead of GPU** (`ollama ps` doesn't show `100% GPU`):
- Check available VRAM with `nvidia-smi` — another process (e.g. a Jellyfin transcode) may be holding memory.
- Check the model isn't larger than available VRAM at its quantization level.

**Open WebUI can't reach Ollama** (model list empty in the UI):
- Confirm both containers are on `ollama_internal`: `docker network inspect ollama_internal`.
- Test directly: `docker exec open-webui curl -s http://ollama:11434/api/tags`.
- Confirm `OLLAMA_BASE_URL=http://ollama:11434` is set on the open-webui service.

**Caddy returns 502 on `ai.example.com`**:
- Check the open-webui container is running and healthy: `docker ps --filter name=open-webui`.
- Check it's still on the `edge` network: `docker network inspect edge`.

**Caddy TLS certificate not issuing**:
- Confirm the `ai` DNS record exists and resolves to the server's public IP, and ports 80/443 are reachable, same as for `media`/`docs`.

**No audio / TTS fails in the UI**:
- Confirm kokoro is running and on `tts_internal`: `docker ps --filter name=kokoro`, `docker network inspect tts_internal`.
- Test connectivity from open-webui: `docker exec open-webui curl -s http://kokoro:8880/health`.
- Confirm the Admin → Audio settings in the UI show engine `OpenAI`, base URL `http://kokoro:8880/v1` (not `localhost`), model `kokoro`, voice `af_bella` — `AUDIO_TTS_*` env vars only take effect the first time that config key is created, so an existing instance may need the UI values set/corrected directly.

**Kokoro fails to start or errors on GPU**:
- The CPU image (`kokoro-fastapi-cpu`) is used deliberately — the GPU image doesn't yet support Blackwell (RTX 5090, `sm_120`); see [upstream issue #365](https://github.com/remsky/Kokoro-FastAPI/issues/365). Don't switch to the GPU image without checking whether that's been resolved upstream.

## Common Commands

Status:

```bash
docker ps --filter name=ollama
docker ps --filter name=open-webui
docker ps --filter name=kokoro
```

Logs:

```bash
cd /srv/apps/ollama && docker compose logs -f
cd /srv/apps/open-webui && docker compose logs -f
cd /srv/apps/kokoro && docker compose logs -f
```

GPU:

```bash
docker exec ollama nvidia-smi
docker exec ollama ollama ps
```

Networks:

```bash
docker network inspect ollama_internal
docker network inspect tts_internal
docker network inspect edge
```

Networks:

```bash
docker network inspect ollama_internal
docker network inspect edge
```
