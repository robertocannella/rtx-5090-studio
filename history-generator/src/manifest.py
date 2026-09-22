import json
import os
import re
import tempfile


def slugify(text):
    s = text.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-") or "episode"


def episode_paths(base_output_dir, slug):
    root = os.path.join(base_output_dir, slug)
    return {
        "root": root,
        "manifest": os.path.join(root, "manifest.json"),
        "outline": os.path.join(root, "outline.json"),
        "scripts": os.path.join(root, "scripts"),
        "audio": os.path.join(root, "audio"),
        "video": os.path.join(root, "video"),
        "images": os.path.join(root, "images"),
        "final": os.path.join(root, "final"),
    }


def ensure_dirs(paths):
    for key in ("root", "scripts", "audio", "video", "images", "final"):
        os.makedirs(paths[key], exist_ok=True)


def load_manifest(path):
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


def save_manifest(path, manifest_data):
    d = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".manifest-", suffix=".json")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(manifest_data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
