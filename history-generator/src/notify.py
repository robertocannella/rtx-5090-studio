"""Push notifications via a self-hosted ntfy instance.

Best-effort only: a notification failure must never take down a job that
otherwise succeeded, so every function here swallows its own errors.
"""

import os

import requests

NTFY_URL = os.environ.get("NTFY_URL", "").rstrip("/")
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")
NTFY_TOKEN = os.environ.get("NTFY_TOKEN", "")


def _enabled():
    return bool(NTFY_URL and NTFY_TOPIC and NTFY_TOKEN)


def send(title, message, tags=None, priority=3):
    if not _enabled():
        return
    headers = {
        "Title": title,
        "Priority": str(priority),
        "Authorization": f"Bearer {NTFY_TOKEN}",
    }
    if tags:
        headers["Tags"] = tags
    try:
        requests.post(
            f"{NTFY_URL}/{NTFY_TOPIC}",
            data=message.encode("utf-8"),
            headers=headers,
            timeout=10,
        )
    except Exception:  # noqa: BLE001 - notifications are best-effort
        pass


def job_complete(slug, title, narration_seconds, target_duration_seconds, failed_count):
    msg = f'"{title}" is ready — {narration_seconds:.0f}s narration'
    if failed_count:
        msg += f" ({failed_count} segment(s) failed and were skipped)"
    send(f"History episode ready: {slug}", msg, tags="white_check_mark,clapper", priority=4)


def job_failed(slug, error):
    send(f"History episode failed: {slug}", error[:400], tags="x", priority=4)
