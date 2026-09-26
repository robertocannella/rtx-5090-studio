import pytest
import db


def test_create_and_get_post_by_slug():
    post_id = db.create_post("My Title", "Physics", "Intro.\n\n<!-- more -->\n\nBody text.")
    post = db.get_post(slug="my-title")
    assert post["id"] == post_id
    assert post["title"] == "My Title"
    assert post["category"] == "Physics"
    assert "Body text." in post["body_html"]
    assert "Intro." in post["excerpt_html"]
    assert "Body text." not in post["excerpt_html"]  # excerpt stops before <!-- more -->


def test_create_post_rejects_duplicate_slug():
    db.create_post("Same Title", "Physics", "First.")
    with pytest.raises(db.PostError):
        db.create_post("Same Title", "Physics", "Second.")


def test_create_post_with_explicit_created_at_preserves_it():
    # migrate_posts.py relies on this to preserve each existing post's real original
    # date instead of resetting it to "now" and scrambling chronological order.
    post_id = db.create_post("Old Post", "Physics", "Body.", created_at="2026-01-01T00:00:00+00:00")
    post = db.get_post(post_id=post_id)
    assert post["created_at"] == "2026-01-01T00:00:00+00:00"
    assert post["updated_at"] != "2026-01-01T00:00:00+00:00"  # updated_at is still "now"


def test_custom_slug_overrides_the_generated_one():
    db.create_post("A Title", "Physics", "Body.", slug="custom-slug")
    assert db.get_post(slug="custom-slug") is not None
    assert db.get_post(slug="a-title") is None


def test_update_post_rerenders_html_when_body_changes():
    post_id = db.create_post("Title", "Physics", "Old body.")
    db.update_post(post_id, body_markdown="New body.")
    post = db.get_post(post_id=post_id)
    assert "New body." in post["body_html"]
    assert "Old body." not in post["body_html"]


def test_update_post_leaves_html_untouched_when_body_not_given():
    post_id = db.create_post("Title", "Physics", "Original body.")
    db.update_post(post_id, title="New Title")
    post = db.get_post(post_id=post_id)
    assert post["title"] == "New Title"
    assert "Original body." in post["body_html"]


def test_update_post_raises_for_unknown_id():
    with pytest.raises(db.PostError):
        db.update_post(99999, title="Doesn't exist")


def test_delete_post_removes_it():
    post_id = db.create_post("Title", "Physics", "Body.")
    db.delete_post(post_id)
    assert db.get_post(post_id=post_id) is None


def test_list_posts_ordered_newest_first_and_filterable_by_category():
    db.create_post("First", "Physics", "Body.")
    db.create_post("Second", "Algebra", "Body.")
    db.create_post("Third", "Physics", "Body.")

    all_posts = db.list_posts()
    assert [p["title"] for p in all_posts] == ["Third", "Second", "First"]

    physics_only = db.list_posts(category="Physics")
    assert [p["title"] for p in physics_only] == ["Third", "First"]


def test_list_categories_returns_distinct_sorted_categories():
    db.create_post("A", "Physics", "Body.")
    db.create_post("B", "Algebra", "Body.")
    db.create_post("C", "Physics", "Body.")
    assert db.list_categories() == ["Algebra", "Physics"]


def test_slugify_handles_punctuation_and_spaces():
    assert db.slugify("Hello, World!") == "hello-world"
    assert db.slugify("  Multiple   Spaces  ") == "multiple-spaces"
