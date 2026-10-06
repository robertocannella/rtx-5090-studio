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


def test_chatgpt_style_bracket_math_renders_without_blank_lines():
    # No blank lines around \[ ... \], matching exactly how ChatGPT outputs display math
    # -- must still render as real math, not literal "[x]" text (see render.py's
    # normalize_display_math_spacing for why this fails without that step).
    body = "Speed is:\n\\[\nv=12\\text{ m/s}\n\\]\nThat is the answer."
    post_id = db.create_post("Bracket Math Post", "Physics", body)
    post = db.get_post(post_id=post_id)
    assert 'class="arithmatex"' in post["body_html"]
    assert "<p>[" not in post["body_html"]


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


def test_create_post_normalizes_tags():
    # Whitespace trimmed, empties dropped, case-insensitive duplicates collapsed to
    # whichever casing was typed first (see db._normalize_tags).
    post_id = db.create_post(
        "Tagged", "Physics", "Body.", tags=[" Limits ", "", "limits", "Continuity"],
    )
    post = db.get_post(post_id=post_id)
    assert post["tags"] == ["Limits", "Continuity"]


def test_create_post_accepts_comma_separated_tags_string():
    # The admin form submits one comma-separated string, not a list -- same normalization
    # rules apply either way.
    post_id = db.create_post("Tagged", "Physics", "Body.", tags="limits, continuity ,, limits")
    post = db.get_post(post_id=post_id)
    assert post["tags"] == ["limits", "continuity"]


def test_create_post_with_no_tags_defaults_to_empty_list():
    post_id = db.create_post("Untagged", "Physics", "Body.")
    post = db.get_post(post_id=post_id)
    assert post["tags"] == []


def test_update_post_changes_tags():
    post_id = db.create_post("Tagged", "Physics", "Body.", tags="limits")
    db.update_post(post_id, tags="continuity, derivatives")
    post = db.get_post(post_id=post_id)
    assert post["tags"] == ["continuity", "derivatives"]


def test_update_post_without_tags_argument_leaves_tags_unchanged():
    post_id = db.create_post("Tagged", "Physics", "Body.", tags="limits")
    db.update_post(post_id, title="Retitled")
    post = db.get_post(post_id=post_id)
    assert post["tags"] == ["limits"]


def test_update_post_can_clear_tags_with_empty_string():
    post_id = db.create_post("Tagged", "Physics", "Body.", tags="limits")
    db.update_post(post_id, tags="")
    post = db.get_post(post_id=post_id)
    assert post["tags"] == []


def test_list_posts_filters_by_tag_case_insensitively():
    db.create_post("A", "Physics", "Body.", tags="Constant Acceleration")
    db.create_post("B", "Physics", "Body.", tags="limits")
    posts = db.list_posts(tag="constant acceleration")
    assert [p["title"] for p in posts] == ["A"]


def test_list_tags_distinct_case_insensitive_and_sorted():
    db.create_post("A", "Physics", "Body.", tags="Limits, Continuity")
    db.create_post("B", "Physics", "Body.", tags="limits, Derivatives")
    assert db.list_tags() == ["Continuity", "Derivatives", "Limits"]


def test_create_post_normalizes_crlf_line_endings():
    # HTML <textarea> submissions always use \r\n, regardless of OS -- a matplotlib
    # fenced block must still be recognized (its regex matches a literal \n).
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
    body = "Line one.\r\n\r\nLine two.\r\n"
    db.update_post(post_id, body_markdown=body)
    post = db.get_post(post_id=post_id)
    assert "\r" not in post["body_markdown"]
    assert "Line two." in post["body_html"]


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


def test_save_and_get_draft_roundtrip():
    db.save_draft("new:abc123", "My Title", "Physics", "tag1, tag2", ["Paragraph one.", "Paragraph two."])
    draft = db.get_draft("new:abc123")
    assert draft["title"] == "My Title"
    assert draft["category"] == "Physics"
    assert draft["tags"] == "tag1, tag2"
    assert draft["segments"] == ["Paragraph one.", "Paragraph two."]
    assert draft["updated_at"]


def test_get_draft_returns_none_when_missing():
    assert db.get_draft("post:999") is None


def test_save_draft_replaces_not_accumulates():
    # Every autosave tick should overwrite the same row, not insert a new one -- a
    # two-minute interval left running for hours must never grow the table unbounded.
    db.save_draft("post:1", "First", "Meta", "", ["a"])
    db.save_draft("post:1", "Second", "Meta", "", ["a", "b"])
    draft = db.get_draft("post:1")
    assert draft["title"] == "Second"
    assert draft["segments"] == ["a", "b"]

    conn = db.get_connection()
    count = conn.execute("SELECT COUNT(*) AS n FROM drafts WHERE key = 'post:1'").fetchone()["n"]
    conn.close()
    assert count == 1


def test_draft_never_touches_the_posts_table():
    # The whole point of a separate table -- an autosave must be structurally incapable
    # of overwriting (or even referencing) a real, already-saved post.
    post_id = db.create_post("Real Post", "Physics", "Original body.")
    db.save_draft(f"post:{post_id}", "Hijacked Title", "Hijacked Category", "", ["Hijacked body."])
    post = db.get_post(post_id=post_id)
    assert post["title"] == "Real Post"
    assert "Original body." in post["body_markdown"]


def test_delete_draft_removes_it():
    db.save_draft("new:xyz", "Title", "Meta", "", ["text"])
    db.delete_draft("new:xyz")
    assert db.get_draft("new:xyz") is None


def test_delete_draft_on_missing_key_is_a_no_op():
    db.delete_draft("post:no-such-key")  # must not raise
