import json

import pytest

import db


def test_create_and_get_post_roundtrip():
    post_id = db.create_post("My Post", "Physics", "Some body text.")
    post = db.get_post(post_id=post_id)
    assert post["title"] == "My Post"
    assert post["slug"] == "my-post"
    assert post["category"] == "Physics"
    assert "Some body text." in post["body_html"]
    assert json.loads(post["toc_json"]) == []
    assert post["reading_minutes"] >= 1


def test_slugify_from_title_when_not_given():
    assert db.slugify("Constant Acceleration: Airplane Takeoff!") == "constant-acceleration-airplane-takeoff"


def test_create_post_with_explicit_slug():
    post_id = db.create_post("Title", "Meta", "Body.", slug="custom-slug")
    post = db.get_post(post_id=post_id)
    assert post["slug"] == "custom-slug"


def test_duplicate_slug_raises():
    db.create_post("First", "Meta", "Body.", slug="dup")
    with pytest.raises(db.DuplicateSlugError):
        db.create_post("Second", "Meta", "Body.", slug="dup")


def test_update_post_changes_fields():
    post_id = db.create_post("Original", "Meta", "Original body.")
    db.update_post(post_id, title="Updated", body_markdown="New body.")
    post = db.get_post(post_id=post_id)
    assert post["title"] == "Updated"
    assert "New body." in post["body_html"]
    assert post["category"] == "Meta"  # unchanged


def test_update_nonexistent_post_raises():
    with pytest.raises(db.PostNotFoundError):
        db.update_post(9999, title="X")


def test_delete_post_removes_it():
    post_id = db.create_post("Gone", "Meta", "Body.")
    db.delete_post(post_id)
    assert db.get_post(post_id=post_id) is None


def test_list_posts_ordered_newest_first():
    id1 = db.create_post("Old", "Meta", "Body.", created_at="2020-01-01T00:00:00+00:00")
    id2 = db.create_post("New", "Meta", "Body.", created_at="2024-01-01T00:00:00+00:00")
    posts = db.list_posts()
    assert [p["id"] for p in posts] == [id2, id1]


def test_list_posts_filters_by_category():
    db.create_post("A", "Physics", "Body.")
    db.create_post("B", "Meta", "Body.")
    posts = db.list_posts(category="Physics")
    assert len(posts) == 1
    assert posts[0]["title"] == "A"


def test_list_categories_distinct_and_sorted():
    db.create_post("A", "Physics", "Body.")
    db.create_post("B", "Meta", "Body.")
    db.create_post("C", "Physics", "Body.")
    assert db.list_categories() == ["Meta", "Physics"]


def test_create_post_normalizes_crlf_line_endings():
    # HTML <textarea> submissions always use \r\n, regardless of OS -- a matplotlib or
    # latex fenced block must still be recognized (their regexes match a literal \n).
    body = (
        'Intro.\r\n\r\n```matplotlib name="crlf-test"\r\n'
        "ax = plt.gca()\r\nax.plot([0, 1], [0, 1])\r\n```"
    )
    post_id = db.create_post("CRLF Post", "Meta", body)
    post = db.get_post(post_id=post_id)
    assert "\r" not in post["body_markdown"]
    assert 'data-plot="crlf-test"' in post["body_html"]


def test_update_post_normalizes_crlf_line_endings():
    post_id = db.create_post("CRLF Update", "Meta", "Original.")
    body = '```latex\r\n\\frac{a}{b}\r\n```'
    db.update_post(post_id, body_markdown=body)
    post = db.get_post(post_id=post_id)
    assert "\r" not in post["body_markdown"]
    assert 'class="arithmatex"' in post["body_html"]


def test_latex_block_renders_as_display_math():
    post_id = db.create_post(
        "Latex Block Post", "Meta",
        '```latex\n\\frac{a}{b}\n```',
    )
    post = db.get_post(post_id=post_id)
    assert "```latex" not in post["body_html"]
    assert 'class="arithmatex"' in post["body_html"]
    assert "\\frac{a}{b}" in post["body_html"]


def test_toc_json_reflects_headings_in_body():
    post_id = db.create_post("With Headings", "Meta", "## Section One\n\nText.\n\n## Section Two\n\nMore.")
    post = db.get_post(post_id=post_id)
    toc = json.loads(post["toc_json"])
    names = [t["name"] for t in toc]
    assert names == ["Section One", "Section Two"]


def test_init_db_backfills_missing_toc_columns(tmp_path, monkeypatch):
    """Simulates a pre-toc_json database (like the one migrated earlier this session)
    to confirm init_db() adds the columns and computes real values, not just defaults.
    """
    import sqlite3

    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE posts (
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
    conn.execute(
        "INSERT INTO posts (slug, title, category, body_markdown, body_html, excerpt_html, created_at, updated_at) "
        "VALUES ('legacy', 'Legacy', 'Meta', '## A Heading\n\nText.', '', '', '2020-01-01', '2020-01-01')"
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(db, "DB_PATH", str(db_path))
    db.init_db()

    post = db.get_post(slug="legacy")
    toc = json.loads(post["toc_json"])
    assert toc[0]["name"] == "A Heading"
    assert post["reading_minutes"] >= 1
    assert "Text." in post["body_html"]
