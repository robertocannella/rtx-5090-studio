"""Private post-management API for math-notes -- create/update/delete/list posts.
Joins only `mathnotes_internal` (see compose.yaml), a private Docker network shared with
history-ui only, never `edge` -- never reachable from the public internet, unlike
public_app.py. history-ui's Configuration UI (a new "Math Notes" tab) is the only client;
gated the same way that whole UI is, by Caddy's basic_auth on generator.example.com.

Shares the same SQLite database file as public_app.py (see db.py) -- writes made here are
immediately visible to the public app's reads, no HTTP call between the two services.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

import db
import render_plots


@asynccontextmanager
async def lifespan(app):
    db.init_db()
    yield


app = FastAPI(title="Math Notes Admin API", lifespan=lifespan)


class CreatePostRequest(BaseModel):
    title: str
    category: str
    body_markdown: str
    slug: str | None = None


class UpdatePostRequest(BaseModel):
    title: str | None = None
    category: str | None = None
    body_markdown: str | None = None


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/posts")
def list_posts():
    return db.list_posts()


@app.get("/categories")
def list_categories():
    return db.list_categories()


@app.get("/posts/{post_id}")
def get_post(post_id: int):
    post = db.get_post(post_id=post_id)
    if not post:
        raise HTTPException(status_code=404, detail=f"no post with id {post_id}")
    return post


@app.post("/posts", status_code=201)
def create_post(req: CreatePostRequest):
    title = req.title.strip()
    category = req.category.strip()
    if not title:
        raise HTTPException(status_code=422, detail="title must not be empty")
    if not category:
        raise HTTPException(status_code=422, detail="category must not be empty")
    if not req.body_markdown.strip():
        raise HTTPException(status_code=422, detail="body_markdown must not be empty")

    try:
        post_id = db.create_post(title, category, req.body_markdown, slug=req.slug)
    except db.DuplicateSlugError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except render_plots.PlotError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return db.get_post(post_id=post_id)


@app.patch("/posts/{post_id}")
def update_post(post_id: int, req: UpdatePostRequest):
    if req.title is not None and not req.title.strip():
        raise HTTPException(status_code=422, detail="title must not be empty")
    if req.category is not None and not req.category.strip():
        raise HTTPException(status_code=422, detail="category must not be empty")
    if req.body_markdown is not None and not req.body_markdown.strip():
        raise HTTPException(status_code=422, detail="body_markdown must not be empty")

    try:
        db.update_post(post_id, title=req.title, category=req.category, body_markdown=req.body_markdown)
    except db.PostNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except render_plots.PlotError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return db.get_post(post_id=post_id)


@app.delete("/posts/{post_id}")
def delete_post(post_id: int):
    if not db.get_post(post_id=post_id):
        raise HTTPException(status_code=404, detail=f"no post with id {post_id}")
    db.delete_post(post_id)
    return {"status": "deleted", "id": post_id}
