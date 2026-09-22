#!/usr/bin/env python3
"""Download an approved set of music tracks into a local audio library."""

import argparse
import csv
import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen


DEFAULT_OUTPUT = Path("/srv/media/audio/music")
CATEGORIES = {
    "sleep-ambient",
    "soft-piano",
    "space",
    "ocean",
    "historical",
}


def safe_filename(value):
    return re.sub(r"[^a-z0-9_-]+", "-", value.lower()).strip("-")[:80]


def probe_duration(path):
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-select_streams", "a:0",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(result.stdout.strip())


def download(url, destination, max_bytes):
    if urlparse(url).scheme != "https":
        raise ValueError("Only HTTPS download URLs are supported")

    request = Request(
        url,
        headers={"User-Agent": "PersonalMusicLibrarySeeder/1.0"},
    )

    with urlopen(request, timeout=60) as response:
        with destination.open("wb") as output:
            total = 0

            while chunk := response.read(256 * 1024):
                total += len(chunk)
                if total > max_bytes:
                    raise ValueError("Track exceeds maximum download size")
                output.write(chunk)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("csv_file", type=Path)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--max-mb", type=int, default=100)
    args = parser.parse_args()

    if args.max_mb < 1:
        parser.error("--max-mb must be positive")

    args.output.mkdir(parents=True, exist_ok=True)
    catalog_path = args.output / "catalog.json"

    catalog = (
        json.loads(catalog_path.read_text())
        if catalog_path.exists()
        else []
    )
    existing_ids = {item["id"] for item in catalog}

    with args.csv_file.open(newline="", encoding="utf-8-sig") as source:
        reader = csv.DictReader(source)

        required = {
            "title", "category", "download_url", "source_url",
            "creator", "license", "tags",
        }
        if not required.issubset(reader.fieldnames or []):
            raise ValueError(
                f"CSV must include columns: {', '.join(sorted(required))}"
            )

        for row in reader:
            title = row["title"].strip()
            category = row["category"].strip()
            url = row["download_url"].strip()

            if category not in CATEGORIES:
                print(f"Skipping {title}: unknown category {category}")
                continue

            if not title or not url or not row["license"].strip():
                print(f"Skipping incomplete entry: {title}")
                continue

            track_id = hashlib.sha256(url.encode()).hexdigest()[:16]

            if track_id in existing_ids:
                print(f"Already downloaded: {title}")
                continue

            folder = args.output / category
            folder.mkdir(parents=True, exist_ok=True)

            # Preserve the URL's extension when it is a known audio type.
            suffix = Path(urlparse(url).path).suffix.lower()
            if suffix not in {".mp3", ".wav", ".flac", ".ogg", ".m4a"}:
                suffix = ".mp3"

            filename = f"{track_id}-{safe_filename(title)}{suffix}"
            destination = folder / filename

            fd, temporary_name = tempfile.mkstemp(
                prefix=".download-",
                suffix=suffix,
                dir=folder,
            )
            os.close(fd)
            temporary = Path(temporary_name)

            try:
                print(f"Downloading: {title}")
                download(url, temporary, args.max_mb * 1024 * 1024)
                duration = probe_duration(temporary)

                if duration <= 0:
                    raise ValueError("Audio has no valid duration")

                temporary.replace(destination)

                entry = {
                    "id": track_id,
                    "title": title,
                    "category": category,
                    "file": str(destination.relative_to(args.output)),
                    "creator": row["creator"].strip(),
                    "source_url": row["source_url"].strip(),
                    "license": row["license"].strip(),
                    "tags": [
                        tag.strip()
                        for tag in row["tags"].split("|")
                        if tag.strip()
                    ],
                    "duration_seconds": round(duration, 2),
                }

                catalog.append(entry)
                existing_ids.add(track_id)

                temp_catalog = catalog_path.with_suffix(".json.tmp")
                temp_catalog.write_text(
                    json.dumps(catalog, indent=2, ensure_ascii=False) + "\n"
                )
                temp_catalog.replace(catalog_path)

                print(f"Saved: {destination}")

            except Exception as error:
                print(f"Failed: {title}: {error}")

            finally:
                temporary.unlink(missing_ok=True)

    print(f"\nCatalog: {catalog_path}")
    print(f"Total tracks: {len(catalog)}")


if __name__ == "__main__":
    main()
