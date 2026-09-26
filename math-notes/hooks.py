"""Build-time MkDocs hook (see mkdocs.yml's `hooks:`) that scans every blog post's YAML
frontmatter for its `categories` list, so the categories sidebar (overrides/main.html)
can list every category that actually exists without hand-maintaining that list -- add a
new category to a post's frontmatter and it just shows up on the next build.

Runs in `on_files`, before any page is rendered, and reads raw frontmatter straight off
disk rather than relying on `Page.meta` (which isn't guaranteed populated for every page
yet at this point in the build) -- simple and unambiguous about when it runs.
"""

from pathlib import Path

import yaml


def on_files(files, config):
    categories = set()
    for f in files:
        if not (f.src_uri.startswith("blog/posts/") and f.src_uri.endswith(".md")):
            continue
        text = Path(f.abs_src_path).read_text(encoding="utf-8")
        if not text.startswith("---"):
            continue
        end = text.find("\n---", 3)
        if end == -1:
            continue
        frontmatter = yaml.safe_load(text[3:end]) or {}
        categories.update(frontmatter.get("categories") or [])

    config.extra["all_categories"] = sorted(categories)
    return files
