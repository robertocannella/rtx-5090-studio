import pytest
from fastapi.testclient import TestClient

import db
import public_app


@pytest.fixture
def client():
    with TestClient(public_app.app) as c:
        yield c


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_home_page(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Math Notes" in resp.text


def test_latex_guide_page_renders_markdown(client):
    resp = client.get("/latex-guide/")
    assert resp.status_code == 200
    assert "LaTeX Guide" in resp.text
    # arithmatex normalizes $...$ to \(...\) in its output for the client-side renderer,
    # so this checks for that form, not the raw $...$ the guide's source is written in.
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
