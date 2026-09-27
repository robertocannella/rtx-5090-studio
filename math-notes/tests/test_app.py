import pytest
from fastapi.testclient import TestClient

import admin_auth
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


def test_palette_scope_is_pinned_to_site_root_on_every_page(client):
    # __md_scope must resolve the same way regardless of which page happens to load it,
    # otherwise the palette (dark/light) preference and other persisted UI state end up
    # keyed differently per page -- see base.html's comment for the full explanation.
    db.create_post("Scope Test", "Meta", "Body.")
    for path in ("/", "/blog/", "/blog/scope-test/", "/latex-guide/", "/admin/"):
        resp = client.get(path)
        assert '__md_scope=new URL("/",location)' in resp.text, path


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
    db.create_post("My First Post", "Physics", "Intro.\n\n<!-- more -->\n\nFull body text.")
    resp = client.get("/blog/my-first-post/")
    assert resp.status_code == 200
    assert "My First Post" in resp.text
    assert "Full body text." in resp.text
    assert 'class="md-content md-content--post"' in resp.text


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
        data={"title": "New Post", "category": "Meta", "segments": ["Body text."]},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/admin/"
    assert client.get("/blog/new-post/").status_code == 200


def test_admin_create_duplicate_slug_shows_error(client):
    db.create_post("Existing", "Meta", "Body.", slug="dup")
    resp = client.post(
        "/admin/new",
        data={"title": "Other", "category": "Meta", "segments": ["Body."], "slug": "dup"},
    )
    assert resp.status_code == 422
    assert "already exists" in resp.text


def test_admin_create_broken_plot_shows_error(client):
    resp = client.post(
        "/admin/new",
        data={
            "title": "Bad Plot",
            "category": "Meta",
            "segments": ['```matplotlib name="bad"\nthis is not python(((\n```'],
        },
    )
    assert resp.status_code == 422
    assert "matplotlib block" in resp.text


def test_admin_edit_post_redirects_to_view_mode(client):
    post_id = db.create_post("Editable", "Meta", "Old body.")
    resp = client.post(
        f"/admin/{post_id}/edit",
        data={"title": "Edited", "category": "Meta", "segments": ["New body."]},
        follow_redirects=False,
    )
    # Saving switches the page from edit mode to view mode (a rendered read of exactly
    # what was saved, with a way back into Edit) instead of the listing -- so a run of
    # edits doesn't require navigating back to the list and clicking Edit again each time.
    assert resp.status_code == 303
    assert resp.headers["location"] == f"/admin/{post_id}?saved=1"
    post = db.get_post(post_id=post_id)
    assert post["title"] == "Edited"
    assert "New body." in post["body_html"]


def test_admin_edit_form_shows_one_block_per_segment(client):
    body = 'Intro.\n\n!!! question "Problem"\n    Body.\n\n```matplotlib name="g"\nax = plt.gca()\n```'
    post_id = db.create_post("Blocky", "Meta", body)
    resp = client.get(f"/admin/{post_id}/edit")
    assert resp.status_code == 200
    # +1 for the hidden <template>'s own inert textarea (never submitted -- browsers
    # exclude <template> content from forms, unlike a plain count() of the raw HTML).
    assert resp.text.count('name="segments"') == 3 + 1
    assert "Admonition (question)" in resp.text
    assert "Matplotlib graph" in resp.text
    assert "Paragraph" in resp.text


def test_admin_new_form_starts_with_one_empty_block(client):
    resp = client.get("/admin/new")
    assert resp.status_code == 200
    assert resp.text.count('name="segments"') == 1 + 1  # +1 for the hidden <template>


def test_admin_edit_submit_with_multiple_segments_reassembles_body(client):
    post_id = db.create_post("Multi Block", "Meta", "Original.")
    resp = client.post(
        f"/admin/{post_id}/edit",
        data={
            "title": "Multi Block",
            "category": "Meta",
            "segments": ["Intro paragraph.", '!!! question "Problem"\n    What is x?'],
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    post = db.get_post(post_id=post_id)
    assert post["body_markdown"] == 'Intro paragraph.\n\n!!! question "Problem"\n    What is x?'
    assert "Intro paragraph." in post["body_html"]
    assert 'class="admonition question"' in post["body_html"]


def test_admin_edit_form_has_no_preview(client):
    # The edit FORM itself stays a plain form -- the rendered view lives on its own page
    # (/admin/{id}), not appended below the textarea.
    post_id = db.create_post("Existing Post", "Meta", "Already **saved** body.")
    resp = client.get(f"/admin/{post_id}/edit")
    assert resp.status_code == 200
    assert 'class="admin-preview' not in resp.text


def test_admin_view_page_shows_rendered_post_and_actions(client):
    post_id = db.create_post("View Mode Post", "Meta", "Some **bold** body.")
    resp = client.get(f"/admin/{post_id}")
    assert resp.status_code == 200
    assert "<strong>bold</strong>" in resp.text
    assert f'href="/admin/{post_id}/edit"' in resp.text
    assert 'href="/blog/view-mode-post/"' in resp.text
    assert f'action="/admin/{post_id}/delete"' in resp.text
    assert "Saved." not in resp.text  # no ?saved=1 on a plain visit


def test_admin_view_page_shows_saved_banner_after_redirect(client):
    post_id = db.create_post("Saved Banner Post", "Meta", "Body.")
    resp = client.get(f"/admin/{post_id}?saved=1")
    assert resp.status_code == 200
    assert "Saved." in resp.text


def test_admin_view_nonexistent_post_404s(client):
    resp = client.get("/admin/9999")
    assert resp.status_code == 404


def test_admin_new_post_still_redirects_to_listing(client):
    # Only editing an existing post switches to view mode -- creating a brand new post
    # still goes to the listing, since there's no "keep iterating on this one" context yet.
    resp = client.post(
        "/admin/new",
        data={"title": "Fresh Post", "category": "Meta", "segments": ["Body."]},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/admin/"


def test_admin_delete_post(client):
    post_id = db.create_post("Deletable", "Meta", "Body.")
    resp = client.post(f"/admin/{post_id}/delete", follow_redirects=False)
    assert resp.status_code == 303
    assert db.get_post(post_id=post_id) is None


def test_admin_edit_nonexistent_post_404s(client):
    resp = client.get("/admin/9999/edit")
    assert resp.status_code == 404


def test_anonymous_visitor_does_not_see_admin_nav_or_edit_link(client):
    post_id = db.create_post("Anon View", "Meta", "Body.")
    home = client.get("/")
    assert ">Admin<" not in home.text
    post = client.get("/blog/anon-view/")
    assert f'href="/admin/{post_id}/edit"' not in post.text


def test_visiting_admin_sets_the_admin_cookie(client):
    resp = client.get("/admin/")
    assert admin_auth.COOKIE_NAME in resp.cookies


def test_admin_cookie_makes_admin_nav_and_edit_link_visible_on_public_pages(client):
    post_id = db.create_post("Cookie View", "Meta", "Body.")
    client.cookies.set(admin_auth.COOKIE_NAME, admin_auth.make_cookie_value())
    home = client.get("/")
    assert ">Admin<" in home.text
    post = client.get("/blog/cookie-view/")
    assert f'href="/admin/{post_id}/edit"' in post.text


def test_forged_admin_cookie_does_not_grant_admin_visibility(client):
    client.cookies.set(admin_auth.COOKIE_NAME, "9999999999.not-a-real-signature")
    home = client.get("/")
    assert ">Admin<" not in home.text


def test_expired_admin_cookie_does_not_grant_admin_visibility(client):
    # A correctly-signed value (using the module's real signing function, not a guess)
    # but with an expiry timestamp in the past -- must be rejected on expiry, not just
    # on a bad signature.
    expired_at = "1"
    expired_cookie = f"{expired_at}.{admin_auth._sign(expired_at)}"
    client.cookies.set(admin_auth.COOKIE_NAME, expired_cookie)
    home = client.get("/")
    assert ">Admin<" not in home.text
