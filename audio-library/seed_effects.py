#!/usr/bin/env python3
"""
Seed a local sound-effects library using Freesound's API.

Requires:
    FREESOUND_API_KEY environment variable

Output:
    /srv/media/audio/effects/<category>/*.mp3
    /srv/media/audio/effects/catalog.json

Only downloads sounds marked Creative Commons 0 (CC0).
Downloads Freesound's high-quality MP3 previews, not original WAV files.
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen


API_URL = "https://freesound.org/apiv2/search/text/"

SEED_QUERIES = {
    "ocean": [
        "underwater bubbles",
        "ocean waves",
        "underwater ambience",
        "whale call",
        "water splash",
    ],
    "nature": [
        "forest ambience",
        "birds chirping",
        "river flowing",
        "wind in trees",
        "insects night",
    ],
    "weather": [
        "rain ambience",
        "thunder rumble",
        "strong wind",
        "storm ambience",
    ],
    "historical": [
        "horse hooves",
        "wooden door creak",
        "blacksmith hammer",
        "footsteps gravel",
        "fire crackling",
    ],
    "transitions": [
        "cinematic whoosh",
        "soft impact",
        "deep rumble",
        "bell chime",
    ],
}

FIELDS = (
    "id,name,username,license,url,duration,tags,"
    "previews,description"
)

CC0_LICENSE = "http://creativecommons.org/publicdomain/zero/1.0/"


def api_request(url, api_key):
    request = Request(
        url,
        headers={
            "Authorization": f"Token {api_key}",
            "User-Agent": "PersonalAudioLibrarySeeder/1.0",
        },
    )

    with urlopen(request, timeout=30) as response:
        return json.load(response)


def search_sounds(query, api_key, page_size):
    params = {
        "query": query,
        "filter": 'license:"Creative Commons 0" duration:[1 TO 180]',
        "fields": FIELDS,
        "page_size": page_size,
        "sort": "score",
    }

    url = f"{API_URL}?{urlencode(params)}"
    result = api_request(url, api_key)
    return result.get("results", [])


def is_cc0(sound):
    license_url = str(sound.get("license", "")).lower()
    return (
        "creativecommons.org/publicdomain/zero/" in license_url
        or license_url.rstrip("/") == CC0_LICENSE.rstrip("/")
    )


def safe_name(value):
    value = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.lower())
    return value.strip("-")[:70] or "sound"


def download_file(url, destination, max_bytes):
    if urlparse(url).scheme != "https":
        raise ValueError("Refusing non-HTTPS download URL")

    request = Request(
        url,
        headers={"User-Agent": "PersonalAudioLibrarySeeder/1.0"},
    )

    temporary = destination.with_suffix(destination.suffix + ".part")

    try:
        with urlopen(request, timeout=60) as response:
            with temporary.open("wb") as output:
                total = 0

                while True:
                    chunk = response.read(1024 * 256)

                    if not chunk:
                        break

                    total += len(chunk)

                    if total > max_bytes:
                        raise ValueError(
                            f"Download exceeded {max_bytes} bytes"
                        )

                    output.write(chunk)

        if total == 0:
            raise ValueError("Downloaded file was empty")

        temporary.replace(destination)

    finally:
        temporary.unlink(missing_ok=True)


def load_catalog(path):
    if not path.exists():
        return []

    data = json.loads(path.read_text())

    if not isinstance(data, list):
        raise ValueError("Existing catalog must contain a JSON array")

    return data


def save_catalog(path, entries):
    temporary = path.with_suffix(".json.tmp")

    temporary.write_text(
        json.dumps(entries, indent=2, ensure_ascii=False) + "\n"
    )

    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--output",
        default="/srv/media/audio/effects",
        help="Destination directory",
    )

    parser.add_argument(
        "--per-query",
        type=int,
        default=2,
        help="Maximum number of sounds to download per search query",
    )

    parser.add_argument(
        "--max-mb",
        type=int,
        default=15,
        help="Maximum size of an individual preview in MB",
    )

    args = parser.parse_args()

    if args.per_query < 1 or args.max_mb < 1:
        parser.error("--per-query and --max-mb must be positive")

    api_key = os.environ.get("FREESOUND_API_KEY")

    if not api_key:
        sys.exit(
            "Missing FREESOUND_API_KEY. "
            "Set it in your shell before running this script."
        )

    output_root = Path(args.output)
    output_root.mkdir(parents=True, exist_ok=True)

    catalog_path = output_root / "catalog.json"
    catalog = load_catalog(catalog_path)

    existing_ids = {
        str(entry["id"])
        for entry in catalog
        if entry.get("source") == "freesound" and "id" in entry
    }

    added = 0

    for category, queries in SEED_QUERIES.items():
        category_dir = output_root / category
        category_dir.mkdir(parents=True, exist_ok=True)

        for query in queries:
            print(f"\n[{category}] Searching: {query}", flush=True)

            try:
                sounds = search_sounds(
                    query,
                    api_key,
                    page_size=max(10, args.per_query * 5),
                )

            except (HTTPError, URLError, TimeoutError) as error:
                print(f"  Search failed: {error}", flush=True)
                continue

            downloaded_for_query = 0

            for sound in sounds:
                if downloaded_for_query >= args.per_query:
                    break

                sound_id = str(sound.get("id", ""))

                if not sound_id or sound_id in existing_ids:
                    continue

                if not is_cc0(sound):
                    continue

                preview_url = (
                    sound.get("previews", {}).get("preview-hq-mp3")
                )

                if not preview_url:
                    continue

                filename = (
                    f"{sound_id}-"
                    f"{safe_name(sound.get('name', 'sound'))}.mp3"
                )

                destination = category_dir / filename

                try:
                    print(f"  Downloading: {filename}", flush=True)

                    download_file(
                        preview_url,
                        destination,
                        max_bytes=args.max_mb * 1024 * 1024,
                    )

                except (HTTPError, URLError, OSError, ValueError) as error:
                    print(f"  Download failed: {error}", flush=True)
                    continue

                entry = {
                    "id": sound_id,
                    "source": "freesound",
                    "name": sound.get("name", ""),
                    "category": category,
                    "search_query": query,
                    "file": str(destination.relative_to(output_root)),
                    "creator": sound.get("username", ""),
                    "source_url": sound.get("url", ""),
                    "license": sound.get("license", ""),
                    "license_name": "CC0",
                    "duration_seconds": sound.get("duration"),
                    "tags": sound.get("tags", []),
                    "description": sound.get("description", ""),
                    "asset_type": "mp3_preview",
                }

                catalog.append(entry)
                existing_ids.add(sound_id)

                # Save after every successful download so an interrupted
                # run can resume without losing its catalog entries.
                save_catalog(catalog_path, catalog)

                added += 1
                downloaded_for_query += 1

                print("  Saved", flush=True)

                time.sleep(0.5)

    print(
        f"\nDone. Added {added} effects. "
        f"Catalog contains {len(catalog)} entries."
    )
    print(f"Library: {output_root}")
    print(f"Catalog: {catalog_path}")


if __name__ == "__main__":
    main()
