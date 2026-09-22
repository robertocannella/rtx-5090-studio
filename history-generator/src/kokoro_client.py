import time

import requests


class KokoroError(Exception):
    pass


def synthesize(base_url, model, voice, text, speed=1.0, response_format="mp3", retries=3, backoff=5, timeout=120):
    payload = {
        "model": model,
        "voice": voice,
        "input": text,
        "response_format": response_format,
        "speed": speed,
    }
    last_exc = None
    for attempt in range(1, retries + 1):
        try:
            resp = requests.post(f"{base_url}/v1/audio/speech", json=payload, timeout=timeout)
            resp.raise_for_status()
            if not resp.content:
                raise KokoroError("empty audio response")
            return resp.content
        except Exception as e:  # noqa: BLE001 - want to retry on anything and report it
            last_exc = e
            if attempt < retries:
                sleep_s = backoff * attempt
                print(f"     [warn] Kokoro request failed (attempt {attempt}/{retries}): {e}; retrying in {sleep_s:.0f}s")
                time.sleep(sleep_s)
    raise KokoroError(f"Kokoro request failed after {retries} attempts: {last_exc}")


def list_voices(base_url, timeout=15):
    """The voice ids Kokoro actually supports right now, straight from its own catalog
    (id, name, quality grade) -- used to validate a requested voice before spending a
    synthesis call on it, and to drive the voice-sample pre-warm at startup. Never
    hand-maintained as a static list, since Kokoro's own voices can change.
    """
    resp = requests.get(f"{base_url}/v1/audio/voices", timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    return [v["id"] for v in data.get("voices", []) if v.get("id")]
