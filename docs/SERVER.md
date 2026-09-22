# RTX Server Configuration

## Purpose

`rtx` is an Ubuntu Server host used for self-hosted web applications, media delivery, and GPU/AI workloads.

## Host

- Hostname: `rtx`
- OS: Ubuntu Server 24.04 LTS
- GPU: NVIDIA GeForce RTX 5090, 32 GB VRAM
- NVIDIA driver and NVIDIA Container Toolkit are installed.
- Docker containers can access the GPU.

## Storage Layout

```text
/srv/
├── apps/       Docker applications and configuration
├── data/       persistent application data
├── media/      media library
└── backups/    backups
```

Application-specific files should normally live under `/srv/apps/<application>`.

## Networking

The server has a reserved LAN address:

```text
192.168.1.78
```

The router forwards public TCP ports 80 and 443 to the server. UDP 443 is also allowed on the server for HTTP/3.

### Firewall

UFW is enabled with incoming traffic denied by default. Public web traffic is permitted on ports 80 and 443, SSH is permitted, and the Samba ports are permitted for the LAN file share (see [File Sharing (Samba)](#file-sharing-samba)).

Docker-published ports require special care because Docker networking can bypass ordinary UFW filtering. Public application containers therefore should not normally publish their own host ports; access is routed through the gateway instead.

## File Sharing (Samba)

A password-protected SMB/CIFS share exposes `/srv/media` directly to devices on the LAN, so media can be copied onto the server over the network without SSH.

```text
Share name : media
Path       : /srv/media
Access     : read/write, restricted to the Samba user appuser
```

Connect from a LAN client:

```text
Windows      \\rtx\media          or  \\192.168.1.78\media
macOS/Linux  smb://192.168.1.78/media
```

Configuration lives at:

```text
/etc/samba/smb.conf
```

Samba is bound only to the LAN interface (`eno1`), not to Docker's bridge networks. It has no public hostname, no gateway route, and no router port forward — it is LAN-only, and only by virtue of not being exposed externally, since the `ufw allow samba` rule itself is not subnet-restricted.

Set or change the Samba user's password with:

```bash
sudo smbpasswd -a appuser
```

Service status and restart:

```bash
systemctl status smbd nmbd
sudo systemctl restart smbd nmbd
```

## SSH

SSH public-key authentication is enabled. Password and keyboard-interactive SSH authentication are disabled, and direct root login is disabled.

## Docker

Docker Engine and Docker Compose are installed. The normal application pattern is:

```text
/srv/apps/<application>/compose.yaml
```

The user account is a member of the `docker` group. Membership in this group effectively provides root-level control of the host.

## Shared Edge Network

Public-facing services communicate with the gateway over an external Docker bridge network named `edge`.

Create it, if necessary, with:

```bash
docker network create edge
```

An application joins it with:

```yaml
networks:
  - edge

networks:
  edge:
    external: true
```

This lets Caddy address containers by name, such as `jellyfin:8096` or `docs:80`.

## Caddy Gateway

The central gateway lives at:

```text
/srv/apps/gateway
```

It is the only normal public entry point for hosted web applications and owns host ports 80 and 443.

Current routing is conceptually:

```caddy
media.example.com {
    reverse_proxy jellyfin:8096
}

docs.example.com {
    basic_auth {
        roberto <PASSWORD_HASH>
    }

    reverse_proxy docs:80
}
```

Never store a plaintext password in the Caddyfile. Generate a password hash with:

```bash
cd /srv/apps/gateway
docker compose exec caddy caddy hash-password
```

Validate configuration before restarting:

```bash
cd /srv/apps/gateway
docker compose exec caddy caddy validate --config /etc/caddy/Caddyfile
docker compose restart
```

## TLS

Caddy automatically obtains and renews public TLS certificates for configured hostnames.

DNS must resolve the hostname to the server and ports 80/443 must be reachable for normal HTTP ACME validation.

## Cloudflare DNS and DDNS

`example.com` DNS is managed through Cloudflare.

A DDNS updater runs on the server because the home public IPv4 address may change.

Configuration:

```text
/etc/cloudflare-ddns/config
```

Updater:

```text
/usr/local/bin/cloudflare-ddns
```

systemd units:

```text
/etc/systemd/system/cloudflare-ddns.service
/etc/systemd/system/cloudflare-ddns.timer
```

The timer checks approximately every five minutes and updates DNS only when the public IPv4 address changes.

API tokens are secrets and must not be placed in this documentation.

### DNS-only records

Services intended to connect directly to this server use Cloudflare DNS-only records rather than the Cloudflare HTTP proxy. This is especially important for the media service.

## Documentation Site

Documentation lives at:

```text
/srv/apps/docs
```

It uses nginx to serve Docsify. Docsify renders Markdown files in the browser.

Important files include:

```text
/srv/apps/docs/index.html
/srv/apps/docs/README.md
/srv/apps/docs/SERVER.md
/srv/apps/docs/JELLYFIN.md
```

The docs container joins the `edge` network and the gateway proxies `docs.example.com` to `docs:80`.

## Adding Another Application

The preferred pattern is:

1. Create `/srv/apps/<app>`.
2. Create its `compose.yaml`.
3. Join the external `edge` Docker network.
4. Avoid publishing a public host port unless there is a specific reason.
5. Start the application.
6. Add its hostname to the gateway Caddyfile.
7. Create the corresponding DNS record.
8. Validate and restart Caddy.
9. Decide whether Caddy authentication or application-native authentication should protect it.

For example:

```caddy
app.example.com {
    reverse_proxy app:8080
}
```

## Useful Commands

Containers:

```bash
docker ps
docker compose ps
docker compose logs -f
```

Gateway:

```bash
cd /srv/apps/gateway
docker compose logs -f
```

Docker network:

```bash
docker network inspect edge
```

Firewall:

```bash
sudo ufw status verbose
```

DDNS timer:

```bash
systemctl status cloudflare-ddns.timer
journalctl -u cloudflare-ddns.service
```

GPU:

```bash
nvidia-smi
docker exec jellyfin nvidia-smi
```

## Editing

Configuration files on this server are edited with `vi`.
