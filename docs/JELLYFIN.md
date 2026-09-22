# Jellyfin Media Server

## Purpose

Jellyfin provides the browser and streaming interface for the media stored on `rtx`. It replaces the raw directory-style media experience with libraries, search, playback, watch history, resume position, and individual Jellyfin users.

Public URL:

```text
https://media.example.com
```

## Architecture

```text
Internet
   |
media.example.com
   |
Caddy gateway :443
   |
Docker edge network
   |
Jellyfin :8096
   |
/srv/media
```

Jellyfin itself does not publish port 8096 on the host. Caddy reaches it through the shared `edge` Docker network.

## Files

Application directory:

```text
/srv/apps/jellyfin
```

Persistent Jellyfin data:

```text
/srv/apps/jellyfin/config
/srv/apps/jellyfin/cache
```

Media:

```text
/srv/media
```

The media directory is mounted read-only inside Jellyfin as `/media` so Jellyfin cannot modify the source media files.

## Docker Compose

The deployment is based on:

```yaml
services:
  jellyfin:
    image: jellyfin/jellyfin:latest
    container_name: jellyfin
    restart: unless-stopped

    volumes:
      - ./config:/config
      - ./cache:/cache
      - /srv/media:/media:ro

    networks:
      - edge

    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]

networks:
  edge:
    external: true
```

Start or update the service from `/srv/apps/jellyfin`:

```bash
cd /srv/apps/jellyfin
docker compose up -d
```

View logs:

```bash
cd /srv/apps/jellyfin
docker compose logs -f
```

## Gateway Route

The gateway routes the media hostname to Jellyfin:

```caddy
media.example.com {
    reverse_proxy jellyfin:8096
}
```

Jellyfin handles its own user authentication. Caddy Basic Auth is therefore not required on the Jellyfin hostname.

## Libraries

Media is visible to Jellyfin under:

```text
/media
```

The initial physics library can point to:

```text
/media/videos/Physics1Course-Unit1
```

For course or personal videos that should not be identified as commercial movies or television, use an appropriate generic/home-video style library type rather than a movie metadata workflow.

## Authentication

Create individual Jellyfin users rather than sharing the administrator account. Jellyfin can control which libraries each user may access.

Keep the administrator account for administration and use ordinary user accounts for normal viewing when practical.

## Direct Play and Transcoding

The preferred playback path is Direct Play:

```text
original media file
       |
    Jellyfin
       |
     Caddy
       |
     client
```

With Direct Play, Jellyfin sends the existing media without re-encoding it. This minimizes CPU/GPU use and preserves the original media quality.

Transcoding is used when the client cannot directly play the original codec/container or when Jellyfin needs to change characteristics such as resolution or bitrate. The GPU is not required for ordinary Direct Play.

### NVIDIA Hardware Transcoding

The RTX 5090 is used for hardware-accelerated transcoding via NVENC (encode) and NVDEC/CUVID (decode). This is configured in Jellyfin's playback settings, stored at:

```text
/srv/apps/jellyfin/config/config/encoding.xml
```

Key settings:

```xml
<HardwareAccelerationType>nvenc</HardwareAccelerationType>
<EnableHardwareEncoding>true</EnableHardwareEncoding>
<HardwareDecodingCodecs>
  <string>h264</string>
  <string>vc1</string>
  <string>hevc</string>
  <string>mpeg2video</string>
  <string>vp8</string>
  <string>vp9</string>
  <string>av1</string>
</HardwareDecodingCodecs>
```

This can also be changed from the Jellyfin web UI under Dashboard → Playback, which rewrites the same file.

No changes to `compose.yaml` were needed — the existing NVIDIA device reservation already exposes the GPU to the container, and the `nvidia-container-toolkit` on the host injects `NVIDIA_DRIVER_CAPABILITIES=compute,video,utility` automatically.

Verify GPU visibility and encoder/decoder support:

```bash
docker exec jellyfin nvidia-smi
docker exec jellyfin /usr/lib/jellyfin-ffmpeg/ffmpeg -encoders 2>&1 | grep nvenc
docker exec jellyfin /usr/lib/jellyfin-ffmpeg/ffmpeg -decoders 2>&1 | grep cuvid
```

Jellyfin also logs detected hardware codec support on startup (`docker compose logs` — look for "Available decoders"/"Available encoders"/"Available hwaccel types").

## Adding Media

Place media under `/srv/media` in a sensible directory hierarchy, for example:

```text
/srv/media/
├── videos/
│   ├── Physics1Course-Unit1/
│   └── AnotherCourse/
└── other-media/
```

Then add or update a Jellyfin library to point at the corresponding path under `/media`.

Files can be copied onto `/srv/media` directly from another device on the LAN over the Samba share (`\\rtx\media` / `smb://192.168.1.78/media`) instead of using SSH — see [Server Configuration](SERVER.md#file-sharing-samba). Jellyfin will pick up new files the next time it scans the library.

## Security Model

- HTTPS terminates at Caddy.
- Jellyfin handles media-user authentication.
- Jellyfin is not directly exposed through host port 8096.
- `/srv/media` is mounted read-only in the Jellyfin container.
- The Cloudflare record for media remains DNS-only.

## Common Commands

Status:

```bash
docker ps --filter name=jellyfin
```

Logs:

```bash
cd /srv/apps/jellyfin
docker compose logs --tail=100
```

Restart:

```bash
cd /srv/apps/jellyfin
docker compose restart
```

GPU:

```bash
docker exec jellyfin nvidia-smi
```

Check the shared network:

```bash
docker network inspect edge
```

## Future Improvements

Possible later additions include additional libraries, restricted user/library permissions, backups of Jellyfin configuration, and monitoring.
