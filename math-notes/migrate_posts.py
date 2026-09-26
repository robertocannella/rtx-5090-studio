"""One-time migration: imports the posts that used to live as markdown files under the
old MkDocs-based site (docs/blog/posts/*.md -- kept in this repo only for historical
reference now, see math-notes/README.md) into the SQLite database the new dynamic app
reads from. Safe to re-run: skips any file whose slug already has a post in the
database, rather than erroring or duplicating.

This is a one-time host-side tool, not part of the running app -- run it in a throwaway
container with both `src/` and `docs/` mounted, and the real `./data` bind-mounted so it
writes to the actual live database:

    docker run --rm \\
      -v "$PWD/src:/app/src" -v "$PWD/docs:/app/docs" -v "$PWD/migrate_posts.py:/app/migrate_posts.py" \\
      -v "$PWD/data:/app/data" -w /app \\
      -e MATH_NOTES_DB_PATH=/app/data/math-notes.db -e MATH_NOTES_PLOTS_DIR=/app/data/assets/plots \\
      math-notes:local sh -c "pip install --quiet pyyaml && python3 migrate_posts.py"
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

import yaml  # noqa: E402

import db  # noqa: E402

OLD_POSTS_DIR = Path(__file__).parent / "docs" / "blog" / "posts"
FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)


def parse_post_file(path):
    text = path.read_text(encoding="utf-8")
    match = FRONTMATTER_RE.match(text)
    if not match:
        raise ValueError(f"{path}: no YAML frontmatter found")
    frontmatter = yaml.safe_load(match.group(1)) or {}
    body = text[match.end():].lstrip("\n")

    title_match = re.search(r"^#\s+(.+)$", body, re.MULTILINE)
    if not title_match:
        raise ValueError(f"{path}: no H1 title found in body")
    title = title_match.group(1).strip()
    # The H1 itself is removed from the stored body -- post.html renders the title
    # separately (<h1>{{ post.title }}</h1>), so keeping it in body_markdown too would
    # show it twice.
    body = (body[:title_match.start()] + body[title_match.end():]).lstrip("\n")

    categories = frontmatter.get("categories") or ["Uncategorized"]
    category = categories[0]

    date_value = frontmatter.get("date")
    created_at = f"{date_value}T00:00:00+00:00" if date_value else None

    # 2026-09-24-welcome.md -> welcome, matching the new app's /blog/{slug}/ URL scheme
    # (and the cross-links already rewritten in src/latex_guide.md to that same scheme).
    slug = re.sub(r"^\d{4}-\d{2}-\d{2}-", "", path.stem)

    return {"title": title, "category": category, "body_markdown": body, "slug": slug, "created_at": created_at}


def main():
    if not OLD_POSTS_DIR.exists():
        print(f"no old posts directory found at {OLD_POSTS_DIR}, nothing to migrate")
        return 0

    db.init_db()
    migrated = 0
    skipped = 0
    for path in sorted(OLD_POSTS_DIR.glob("*.md")):
        parsed = parse_post_file(path)
        if db.get_post(slug=parsed["slug"]):
            print(f"skip (already migrated): {parsed['slug']}")
            skipped += 1
            continue
        db.create_post(
            parsed["title"], parsed["category"], parsed["body_markdown"],
            slug=parsed["slug"], created_at=parsed["created_at"],
        )
        print(f"migrated: {parsed['slug']} ({parsed['title']!r})")
        migrated += 1

    print(f"done: {migrated} migrated, {skipped} already present")
    return 0


if __name__ == "__main__":
    sys.exit(main())
