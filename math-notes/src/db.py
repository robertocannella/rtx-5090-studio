"""SQLite-backed storage for math-notes posts, shared between the public read-only app
(public_app.py) and the private admin API (admin_app.py) via a bind-mounted database
file (see compose.yaml) -- both containers open the same file directly rather than one
calling the other over HTTP, since SQLite already handles cross-process file locking.

A post's Markdown is rendered to HTML exactly once, here, whenever it's created or
updated (see render.py and render_plots.py) -- every read is then a plain row fetch, no
per-request Markdown parsing or matplotlib execution.
"""

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
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()


def slugify(title):
    s = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return s or "post"


def _now():
    return datetime.now(timezone.utc).isoformat()


def _render(body_markdown):
    excerpt_md, full_md = render.split_excerpt(body_markdown)
    full_md = render_plots.process(full_md, PLOTS_DIR)
    # The excerpt is a prefix of the full text (see split_excerpt) -- reprocessing it
    # through render_plots.process a second time is only a concern if a graph's own
    # `name` somehow appeared before the <!-- more --> marker, which just re-renders the
    # same image to the same path a second time (harmless, not a correctness issue).
    excerpt_md = render_plots.process(excerpt_md, PLOTS_DIR)
    return render.render_markdown(excerpt_md), render.render_markdown(full_md)


def create_post(title, category, body_markdown, slug=None, created_at=None):
    """created_at defaults to now -- only overridden by migrate_posts.py, to preserve
    each existing post's real original date instead of resetting every migrated post to
    "just now" and scrambling the blog's chronological order.
    """
    slug = (slug or "").strip() or slugify(title)
    excerpt_html, body_html = _render(body_markdown)
    now = _now()
    created_at = created_at or now
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO posts (slug, title, category, body_markdown, body_html, excerpt_html, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (slug, title, category, body_markdown, body_html, excerpt_html, created_at, now),
        )
        conn.commit()
        return cur.lastrowid
    except sqlite3.IntegrityError as e:
        raise DuplicateSlugError(f"a post with slug {slug!r} already exists") from e
    finally:
        conn.close()


def update_post(post_id, title=None, category=None, body_markdown=None):
    conn = get_connection()
    row = conn.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()
    if row is None:
        conn.close()
        raise PostNotFoundError(f"no post with id {post_id}")

    new_title = title if title is not None else row["title"]
    new_category = category if category is not None else row["category"]

    if body_markdown is not None:
        excerpt_html, body_html = _render(body_markdown)
        new_body_markdown = body_markdown
    else:
        excerpt_html, body_html, new_body_markdown = row["excerpt_html"], row["body_html"], row["body_markdown"]

    conn.execute(
        "UPDATE posts SET title=?, category=?, body_markdown=?, body_html=?, excerpt_html=?, updated_at=? WHERE id=?",
        (new_title, new_category, new_body_markdown, body_html, excerpt_html, _now(), post_id),
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
    return dict(row) if row else None


def list_posts(category=None):
    conn = get_connection()
    if category:
        rows = conn.execute(
            "SELECT * FROM posts WHERE category = ? ORDER BY created_at DESC", (category,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM posts ORDER BY created_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def list_categories():
    conn = get_connection()
    rows = conn.execute("SELECT DISTINCT category FROM posts ORDER BY category").fetchall()
    conn.close()
    return [r["category"] for r in rows]
