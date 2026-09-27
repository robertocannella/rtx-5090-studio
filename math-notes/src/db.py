"""SQLite-backed storage for math-notes posts (see app.py for the public and /admin
routes that read/write through this module).

A post's Markdown is rendered to HTML exactly once, here, whenever it's created or
updated (see render.py and render_plots.py) -- every read is then a plain row fetch, no
per-request Markdown parsing or matplotlib execution.
"""

import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import render
import render_plots

DB_PATH = os.environ.get("MATH_NOTES_DB_PATH", "/app/data/math-notes.db")
PLOTS_DIR = Path(os.environ.get("MATH_NOTES_PLOTS_DIR", "/app/data/assets/plots"))


class PostError(Exception):
    pass


class PostNotFoundError(PostError):
    pass


class DuplicateSlugError(PostError):
    pass


def get_connection():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    # WAL mode lets the public app's reads proceed without blocking on the admin app's
    # occasional writes (and vice versa) -- the two are separate OS processes in separate
    # containers, not threads in one process, so a plain rollback-journal SQLite database
    # would otherwise serialize far more aggressively than this low-write-volume use case
    # actually needs.
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            slug TEXT UNIQUE NOT NULL,
            title TEXT NOT NULL,
            category TEXT NOT NULL,
            body_markdown TEXT NOT NULL,
            body_html TEXT NOT NULL,
            excerpt_html TEXT NOT NULL,
            toc_json TEXT NOT NULL DEFAULT '[]',
            reading_minutes INTEGER NOT NULL DEFAULT 1,
            tags_json TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    existing_cols = {row["name"] for row in conn.execute("PRAGMA table_info(posts)")}
    added_toc_columns = False
    if "toc_json" not in existing_cols:
        conn.execute("ALTER TABLE posts ADD COLUMN toc_json TEXT NOT NULL DEFAULT '[]'")
        added_toc_columns = True
    if "reading_minutes" not in existing_cols:
        conn.execute("ALTER TABLE posts ADD COLUMN reading_minutes INTEGER NOT NULL DEFAULT 1")
        added_toc_columns = True
    if "tags_json" not in existing_cols:
        # No re-render needed here (unlike toc_json/reading_minutes above) -- '[]' is
        # already the correct, final value for every post that predates tags, not just a
        # placeholder waiting to be backfilled.
        conn.execute("ALTER TABLE posts ADD COLUMN tags_json TEXT NOT NULL DEFAULT '[]'")
    conn.commit()
    if added_toc_columns:
        # Posts migrated from a schema before toc_json/reading_minutes existed (or from
        # the pre-database static site) got the column defaults above -- backfill real
        # values for each one now, in place, without touching created_at/updated_at.
        rows = conn.execute("SELECT id, slug, body_markdown FROM posts").fetchall()
        for row in rows:
            excerpt_html, body_html, toc_json, reading_minutes = _render(row["body_markdown"], row["slug"])
            conn.execute(
                "UPDATE posts SET body_html=?, excerpt_html=?, toc_json=?, reading_minutes=? WHERE id=?",
                (body_html, excerpt_html, toc_json, reading_minutes, row["id"]),
            )
        conn.commit()
    conn.close()


def slugify(title):
    s = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return s or "post"


def _now():
    return datetime.now(timezone.utc).isoformat()


def _normalize_tags(tags):
    """Accepts either a list of tag strings or one comma-separated string (the admin
    form's own representation -- see app.py) and returns a clean list: whitespace
    trimmed, empties dropped, duplicates removed case-insensitively while keeping
    whichever casing was typed first, order otherwise preserved (not alphabetized --
    that's a display-time choice, made by whoever's listing them, e.g. list_tags()).
    """
    if tags is None:
        return []
    if isinstance(tags, str):
        tags = tags.split(",")
    seen_lower = set()
    result = []
    for tag in tags:
        tag = tag.strip()
        if not tag or tag.lower() in seen_lower:
            continue
        seen_lower.add(tag.lower())
        result.append(tag)
    return result


def _row_to_post(row):
    post = dict(row)
    post["tags"] = json.loads(post["tags_json"])
    return post


def _normalize_newlines(text):
    """HTML <textarea> form submissions always use CRLF line endings, regardless of the
    submitting OS (that's the HTML spec's behavior, not a quirk of any one browser) --
    normalized here, once, so render_plots.py's regex (which matches a literal \\n) sees
    plain \\n consistently, whether a post came from the admin form, migrate_posts.py, or
    anywhere else.
    """
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _render(body_markdown, slug):
    """slug scopes where this post's matplotlib graphs get written/served
    (PLOTS_DIR/<slug>/<name>.png, /assets/plots/<slug>/<name>.png) -- a graph's `name`
    only has to be unique *within* one post, not across the whole site, since two
    different posts can never share a slug (enforced by the `posts.slug` UNIQUE
    constraint). slug is used rather than the post's own id because it's already known
    before this ever runs: create_post() computes it before calling this, and an
    existing post's slug never changes on update -- the id, by contrast, doesn't exist
    yet for a brand new post at this point (the INSERT that assigns one hasn't happened).
    """
    post_plots_dir = PLOTS_DIR / slug
    assets_url_prefix = f"/assets/plots/{slug}"

    excerpt_md, full_md = render.split_excerpt(body_markdown)
    full_md = render.normalize_display_math_spacing(full_md)
    full_md = render_plots.process(full_md, post_plots_dir, assets_url_prefix=assets_url_prefix)
    # The excerpt is a prefix of the full text (see split_excerpt) -- reprocessing it
    # through normalize_display_math_spacing/render_plots.process a second time is only a
    # concern if a graph's own `name` somehow appeared before the <!-- more --> marker,
    # which just re-renders the same image to the same path a second time (harmless, not
    # a correctness issue).
    excerpt_md = render.normalize_display_math_spacing(excerpt_md)
    excerpt_md = render_plots.process(excerpt_md, post_plots_dir, assets_url_prefix=assets_url_prefix)
    excerpt_html, _ = render.render_markdown(excerpt_md)
    body_html, toc_tokens = render.render_markdown(full_md)
    reading_minutes = render.reading_time_minutes(body_html)
    return excerpt_html, body_html, json.dumps(toc_tokens), reading_minutes


def create_post(title, category, body_markdown, tags=None, slug=None, created_at=None):
    """created_at defaults to now -- only overridden by migrate_posts.py, to preserve
    each existing post's real original date instead of resetting every migrated post to
    "just now" and scrambling the blog's chronological order.
    """
    slug = (slug or "").strip() or slugify(title)
    body_markdown = _normalize_newlines(body_markdown)
    excerpt_html, body_html, toc_json, reading_minutes = _render(body_markdown, slug)
    tags_json = json.dumps(_normalize_tags(tags))
    now = _now()
    created_at = created_at or now
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO posts (slug, title, category, body_markdown, body_html, excerpt_html, "
            "toc_json, reading_minutes, tags_json, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (slug, title, category, body_markdown, body_html, excerpt_html,
             toc_json, reading_minutes, tags_json, created_at, now),
        )
        conn.commit()
        return cur.lastrowid
    except sqlite3.IntegrityError as e:
        raise DuplicateSlugError(f"a post with slug {slug!r} already exists") from e
    finally:
        conn.close()


def update_post(post_id, title=None, category=None, body_markdown=None, tags=None):
    conn = get_connection()
    row = conn.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()
    if row is None:
        conn.close()
        raise PostNotFoundError(f"no post with id {post_id}")

    new_title = title if title is not None else row["title"]
    new_category = category if category is not None else row["category"]
    new_tags_json = json.dumps(_normalize_tags(tags)) if tags is not None else row["tags_json"]

    if body_markdown is not None:
        body_markdown = _normalize_newlines(body_markdown)
        excerpt_html, body_html, toc_json, reading_minutes = _render(body_markdown, row["slug"])
        new_body_markdown = body_markdown
    else:
        excerpt_html, body_html, new_body_markdown = row["excerpt_html"], row["body_html"], row["body_markdown"]
        toc_json, reading_minutes = row["toc_json"], row["reading_minutes"]

    conn.execute(
        "UPDATE posts SET title=?, category=?, body_markdown=?, body_html=?, excerpt_html=?, "
        "toc_json=?, reading_minutes=?, tags_json=?, updated_at=? WHERE id=?",
        (new_title, new_category, new_body_markdown, body_html, excerpt_html,
         toc_json, reading_minutes, new_tags_json, _now(), post_id),
    )
    conn.commit()
    conn.close()


def delete_post(post_id):
    conn = get_connection()
    conn.execute("DELETE FROM posts WHERE id = ?", (post_id,))
    conn.commit()
    conn.close()


def get_post(slug=None, post_id=None):
    conn = get_connection()
    if slug is not None:
        row = conn.execute("SELECT * FROM posts WHERE slug = ?", (slug,)).fetchone()
    else:
        row = conn.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()
    conn.close()
    return _row_to_post(row) if row else None


def list_posts(category=None, tag=None):
    """tag filtering happens in Python, not SQL -- tags_json is a plain JSON array
    column (see _normalize_tags), and at this site's scale (a handful of posts) a
    per-request Python filter is simpler and just as fast as relying on SQLite's json1
    extension, without needing to confirm that extension is compiled into whatever
    Python/SQLite build this runs on. Matching is case-insensitive, same as
    list_categories()/blog_category's own lookup.
    """
    conn = get_connection()
    if category:
        rows = conn.execute(
            "SELECT * FROM posts WHERE category = ? ORDER BY created_at DESC", (category,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM posts ORDER BY created_at DESC").fetchall()
    conn.close()
    posts = [_row_to_post(r) for r in rows]
    if tag:
        posts = [p for p in posts if tag.lower() in (t.lower() for t in p["tags"])]
    return posts


def list_categories():
    conn = get_connection()
    rows = conn.execute("SELECT DISTINCT category FROM posts ORDER BY category").fetchall()
    conn.close()
    return [r["category"] for r in rows]


def list_tags():
    """Every distinct tag in use, across every post, sorted case-insensitively --
    powers the tags list in the categories panel and validates /blog/tag/{tag}/ lookups
    (see app.py). Case-insensitive dedup keeps whichever casing was stored on the post
    that happened to come back from the database first; two posts spelling the same tag
    differently (\"Limits\" vs \"limits\") intentionally collapse to one entry rather
    than showing both.
    """
    conn = get_connection()
    rows = conn.execute("SELECT tags_json FROM posts").fetchall()
    conn.close()
    seen_lower = {}
    for row in rows:
        for tag in json.loads(row["tags_json"]):
            seen_lower.setdefault(tag.lower(), tag)
    return sorted(seen_lower.values(), key=str.lower)
