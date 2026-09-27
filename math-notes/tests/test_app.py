import pytest
from fastapi.testclient import TestClient

import db
from app import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_home_page_renders_material_chrome(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Math Notes" in resp.text
    assert 'class="md-header"' in resp.text
    assert "assets/stylesheets/main." in resp.text


def test_latex_guide_page_renders_markdown_and_katex(client):
    resp = client.get("/latex-guide/")
    assert resp.status_code == 200
    assert "LaTeX Guide" in resp.text
    assert 'class="arithmatex"' in resp.text
    assert "\\frac{1}{2}" in resp.text


def test_blog_index_empty(client):
    resp = client.get("/blog/")
    assert resp.status_code == 200
    assert "No posts" in resp.text


def test_blog_index_lists_created_post(client):
    db.create_post("My First Post", "Physics", "Intro.\n\n<!-- more -->\n\nBody.")
    resp = client.get("/blog/")
    assert resp.status_code == 200
    assert "My First Post" in resp.text
    assert "Physics" in resp.text
    assert "Intro." in resp.text
    assert "Body." not in resp.text  # index shows the excerpt, not the full post


def test_individual_post_page(client):
    post_id = db.create_post("My First Post", "Physics", "Intro.\n\n<!-- more -->\n\nFull body text.")
    resp = client.get("/blog/my-first-post/")
    assert resp.status_code == 200
    assert "My First Post" in resp.text
    assert "Full body text." in resp.text
    assert 'class="md-content md-content--post"' in resp.text
    assert f'href="/admin/{post_id}/edit"' in resp.text


def test_individual_post_404_for_unknown_slug(client):
    resp = client.get("/blog/does-not-exist/")
    assert resp.status_code == 404


def test_category_page_filters_posts(client):
    db.create_post("Physics Post", "Physics", "Body.")
    db.create_post("Algebra Post", "Algebra", "Body.")
    resp = client.get("/blog/category/physics/")
    assert resp.status_code == 200
    assert "Physics Post" in resp.text
    assert "Algebra Post" not in resp.text


def test_feed_xml_lists_posts(client):
    db.create_post("Feed Post", "Physics", "Body.")
    resp = client.get("/feed.xml")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/rss+xml")
    assert "Feed Post" in resp.text
    assert "<rss" in resp.text


def test_search_index_includes_posts(client):
    db.create_post("Searchable Post", "Physics", "Findable body text.")
    resp = client.get("/search/search_index.json")
    assert resp.status_code == 200
    data = resp.json()
    locations = {d["location"] for d in data["docs"]}
    assert "blog/searchable-post/" in locations


def test_matplotlib_post_renders_button_and_serves_image(client):
    body = (
        '```matplotlib name="test-graph"\n'
        "ax = plt.gca()\n"
        "ax.plot([0, 1], [0, 1])\n"
        "```"
    )
    db.create_post("Graph Post", "Physics", body)
    resp = client.get("/blog/graph-post/")
    assert resp.status_code == 200
    assert 'data-plot="test-graph"' in resp.text

    image_resp = client.get("/assets/plots/test-graph.png")
    assert image_resp.status_code == 200
    assert image_resp.headers["content-type"] == "image/png"


def test_vendor_asset_path_traversal_rejected(client):
    # ".." collapses out of static/vendor entirely, down to a real file (src/app.py) --
    # the route must still refuse it, not just rely on the target not existing.
    resp = client.get("/assets/../../app.py")
    assert resp.status_code == 404


def test_admin_list_shows_posts(client):
    db.create_post("Admin Visible", "Meta", "Body.")
    resp = client.get("/admin/")
    assert resp.status_code == 200
    assert "Admin Visible" in resp.text


def test_admin_pages_render_the_real_site_header(client):
    for path in ("/admin/", "/admin/new"):
        resp = client.get(path)
        assert resp.status_code == 200
        assert 'class="md-header"' in resp.text
        assert "assets/stylesheets/main." in resp.text
        assert 'class="admin-header"' in resp.text


def test_admin_create_post(client):
    resp = client.post(
        "/admin/new",
        data={"title": "New Post", "category": "Meta", "body_markdown": "Body text."},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/admin/"
    assert client.get("/blog/new-post/").status_code == 200


def test_admin_create_duplicate_slug_shows_error(client):
    db.create_post("Existing", "Meta", "Body.", slug="dup")
    resp = client.post(
        "/admin/new",
        data={"title": "Other", "category": "Meta", "body_markdown": "Body.", "slug": "dup"},
    )
    assert resp.status_code == 422
    assert "already exists" in resp.text


def test_admin_create_broken_plot_shows_error(client):
    resp = client.post(
        "/admin/new",
        data={
            "title": "Bad Plot",
            "category": "Meta",
            "body_markdown": '```matplotlib name="bad"\nthis is not python(((\n```',
        },
    )
    assert resp.status_code == 422
    assert "matplotlib block" in resp.text


def test_admin_edit_post(client):
    post_id = db.create_post("Editable", "Meta", "Old body.")
    resp = client.post(
        f"/admin/{post_id}/edit",
        data={"title": "Edited", "category": "Meta", "body_markdown": "New body."},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    post = db.get_post(post_id=post_id)
    assert post["title"] == "Edited"
    assert "New body." in post["body_html"]


def test_admin_delete_post(client):
    post_id = db.create_post("Deletable", "Meta", "Body.")
    resp = client.post(f"/admin/{post_id}/delete", follow_redirects=False)
    assert resp.status_code == 303
    assert db.get_post(post_id=post_id) is None


def test_admin_edit_nonexistent_post_404s(client):
    resp = client.get("/admin/9999/edit")
    assert resp.status_code == 404
