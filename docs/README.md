# RTX Server Documentation

This site documents the services running on the `rtx` Ubuntu server.

## Documentation

- [Server Configuration](SERVER.md) — host, networking, Docker, Caddy, Cloudflare DDNS, firewall, storage, and how to add services.
- [Jellyfin Media Server](JELLYFIN.md) — Jellyfin deployment, media storage, authentication, and playback architecture.
- [Ollama + Open WebUI](OLLAMA.md) — local AI stack, GPU-backed model inference, compose files, and model management.
- [History Generator](HISTORY-GENERATOR.md) — batch pipeline that turns a topic into a ~60-minute narrated history video using Qwen, Kokoro, and FFmpeg.
- [Math Notes](MATH-NOTES.md) — public MkDocs/KaTeX blog for math notes and worked word problems.

## Current Services

| Service | Public hostname | Purpose |
|---|---|---|
| Jellyfin | `media.example.com` | Private media browser and streaming |
| Documentation | `docs.example.com` | Server documentation |
| Ollama / Open WebUI | `ai.example.com` | Local AI chat, GPU-backed inference |
| History Generator | *(private API + CLI only — no direct hostname; used via the tool/UI below)* | Batch pipeline generating ~60-minute narrated history/math/discovery MP4s from Qwen + Kokoro + FFmpeg |
| History Generator — Open WebUI tool | *(via `ai.example.com` chat)* | Trigger/check episodes conversationally, from `qwen3:32b` chat |
| History Generator — Configuration UI | `generator.example.com` (`basic_auth`) | Browser form to configure, start, and track episodes without a chat prompt |
| ComfyUI | *(private, no hostname — reached only by History Generator)* | Local FLUX.1-schnell image generation, GPU-backed, used by History Generator's `visual_style="images"` |
| ntfy | `ntfy.example.com` | Private push notifications (currently: history-generator job completion) |
| Samba file share | `\\rtx\media` (LAN only) | Read/write network access to `/srv/media` for uploading files directly |
| Math Notes | `math.example.com` (public) | MkDocs/Material blog for math notes and worked word problems, with LaTeX via KaTeX |

## Architecture

```text
Internet
   |
Router :80/:443
   |
Caddy Gateway
   +-- media.example.com     --> Jellyfin
   +-- docs.example.com      --> Docsify/nginx
   +-- ai.example.com        --> Open WebUI --> Ollama (private network)
   +-- ntfy.example.com      --> ntfy (deny-all auth; push notifications)
   +-- generator.example.com --> history-ui (basic_auth) --> history-api (private network)
   +-- math.example.com      --> math-notes (public, static nginx)

Docker network: edge (Open WebUI additionally bridges three private networks: ollama_internal and tts_internal — see OLLAMA.md — and historygen_internal, to reach the history-api service — see HISTORY-GENERATOR.md. history-ui, the Configuration UI, also bridges historygen_internal and tts_internal the same way, so it can reach history-api and Kokoro's voice list — see HISTORY-GENERATOR.md. History Generator (both history-generator and history-api) additionally bridges comfyui_internal, a private network shared only with the standalone comfyui service, for AI-generated segment images — see HISTORY-GENERATOR.md)

Persistent data
   /srv/apps   application configuration
   /srv/media  media files (also reachable directly via Samba, LAN only)
   /srv/data   application data
   /srv/backups backups
```

## Adding Documentation

Create another Markdown file in `/srv/apps/docs`, add a link to it above, and add a matching bind mount line to `compose.yaml` (each file is mounted individually, not the whole directory). Docsify renders Markdown directly, so no site build is required.

Docker bind-mounts a single file by inode. If a file is edited by replacing it (atomic save/rename, rather than writing in place — most editors and tools do this), the running container keeps serving the old, now-orphaned inode and silently goes stale. **After editing any mounted `.md` file, recreate the container** rather than just restarting it:

```bash
cd /srv/apps/docs && docker compose up -d --force-recreate
```

A plain `docker compose restart` does not fix this — it restarts the process without re-resolving the bind mounts.
