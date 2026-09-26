import pytest
from fastapi.testclient import TestClient

import admin_app
import db


@pytest.fixture
def client():
    with TestClient(admin_app.app) as c:
        yield c


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200


def test_create_post(client):
    resp = client.post("/posts", json={"title": "New Post", "category": "Physics", "body_markdown": "Body text."})
    assert resp.status_code == 201
    body = resp.json()
    assert body["slug"] == "new-post"
    assert "Body text." in body["body_html"]


def test_create_post_rejects_empty_title(client):
    resp = client.post("/posts", json={"title": "  ", "category": "Physics", "body_markdown": "Body."})
    assert resp.status_code == 422


def test_create_post_rejects_duplicate_slug(client):
    client.post("/posts", json={"title": "Same Title", "category": "Physics", "body_markdown": "First."})
    resp = client.post("/posts", json={"title": "Same Title", "category": "Physics", "body_markdown": "Second."})
    assert resp.status_code == 409


def test_create_post_reports_broken_matplotlib_block_as_422(client):
    body = '```matplotlib name="broken"\nthis is not python(((\n```'
    resp = client.post("/posts", json={"title": "Broken Graph", "category": "Physics", "body_markdown": body})
    assert resp.status_code == 422
    assert "broken" in resp.json()["detail"]


def test_list_posts(client):
    client.post("/posts", json={"title": "First", "category": "Physics", "body_markdown": "Body."})
    client.post("/posts", json={"title": "Second", "category": "Algebra", "body_markdown": "Body."})
    resp = client.get("/posts")
    assert resp.status_code == 200
    titles = [p["title"] for p in resp.json()]
    assert titles == ["Second", "First"]  # newest first


def test_get_single_post(client):
    created = client.post("/posts", json={"title": "A Post", "category": "Physics", "body_markdown": "Body."}).json()
    resp = client.get(f"/posts/{created['id']}")
    assert resp.status_code == 200
    assert resp.json()["title"] == "A Post"


def test_get_post_404_for_unknown_id(client):
    resp = client.get("/posts/999999")
    assert resp.status_code == 404


def test_update_post(client):
    created = client.post("/posts", json={"title": "Old Title", "category": "Physics", "body_markdown": "Old body."}).json()
    resp = client.patch(f"/posts/{created['id']}", json={"title": "New Title", "body_markdown": "New body."})
    assert resp.status_code == 200
    body = resp.json()
    assert body["title"] == "New Title"
    assert "New body." in body["body_html"]


def test_update_post_404_for_unknown_id(client):
    resp = client.patch("/posts/999999", json={"title": "Doesn't matter"})
    assert resp.status_code == 404


def test_update_post_rejects_empty_title(client):
    created = client.post("/posts", json={"title": "Title", "category": "Physics", "body_markdown": "Body."}).json()
    resp = client.patch(f"/posts/{created['id']}", json={"title": "   "})
    assert resp.status_code == 422


def test_delete_post(client):
    created = client.post("/posts", json={"title": "To Delete", "category": "Physics", "body_markdown": "Body."}).json()
    resp = client.delete(f"/posts/{created['id']}")
    assert resp.status_code == 200
    assert db.get_post(post_id=created["id"]) is None


def test_delete_post_404_for_unknown_id(client):
    resp = client.delete("/posts/999999")
    assert resp.status_code == 404


def test_list_categories(client):
    client.post("/posts", json={"title": "A", "category": "Physics", "body_markdown": "Body."})
    client.post("/posts", json={"title": "B", "category": "Algebra", "body_markdown": "Body."})
    resp = client.get("/categories")
    assert resp.status_code == 200
    assert resp.json() == ["Algebra", "Physics"]
