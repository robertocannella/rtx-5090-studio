"""Public, read-only math-notes web app -- serves math.example.com. Joins only
`edge` (see compose.yaml); it has no create/update/delete routes at all, those live in
admin_app.py, a separate service on a private network only history-ui can reach. Both
apps share the same SQLite database file (see db.py) and plot-image directory.
"""

from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import db
import render

BASE_DIR = Path(__file__).parent
SITE_URL = "https://math.example.com"


@asynccontextmanager
async def lifespan(app):
    db.init_db()
    yield


app = FastAPI(title="Math Notes", lifespan=lifespan)
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

# StaticFiles requires its directory to exist at mount time -- a fresh deployment with an
# empty data volume (nothing has ever rendered a matplotlib graph yet) would otherwise
# crash on startup before ever getting the chance to create this directory itself.
db.PLOTS_DIR.parent.mkdir(parents=True, exist_ok=True)
app.mount("/assets", StaticFiles(directory=str(db.PLOTS_DIR.parent)), name="assets")


def _display_date(iso_string):
    return datetime.fromisoformat(iso_string).strftime("%B %-d, %Y")


def _with_display_date(post):
    post = dict(post)
    post["created_at_display"] = _display_date(post["created_at"])
    return post


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/")
def home(request: Request):
    return templates.TemplateResponse(
        request, "index.html", {"active_nav": "home", "categories": db.list_categories()},
    )


@app.get("/blog/")
def blog_index(request: Request):
    posts = [_with_display_date(p) for p in db.list_posts()]
    return templates.TemplateResponse(
        request, "blog_index.html",
        {"active_nav": "blog", "categories": db.list_categories(), "posts": posts, "category": None},
    )


@app.get("/blog/category/{category}/")
def blog_category(request: Request, category: str):
    all_categories = db.list_categories()
    matched = next((c for c in all_categories if c.lower() == category.lower()), None)
    posts = [_with_display_date(p) for p in db.list_posts(category=matched)] if matched else []
    return templates.TemplateResponse(
        request, "blog_index.html",
        {"active_nav": "blog", "categories": all_categories, "posts": posts, "category": matched or category},
    )


@app.get("/blog/{slug}/")
def blog_post(request: Request, slug: str):
    post = db.get_post(slug=slug)
    if not post:
        raise HTTPException(status_code=404, detail="post not found")
    return templates.TemplateResponse(
        request, "post.html",
        {"active_nav": "blog", "categories": db.list_categories(), "post": _with_display_date(post)},
    )


@app.get("/latex-guide/")
def latex_guide(request: Request):
    text = (BASE_DIR / "latex_guide.md").read_text(encoding="utf-8")
    content_html = render.render_markdown(text)
    return templates.TemplateResponse(
        request, "latex_guide.html",
        {"active_nav": "latex-guide", "categories": db.list_categories(), "content_html": content_html},
    )


@app.get("/feed.xml")
def feed():
    posts = db.list_posts()
    items = "\n".join(
        f"<item>"
        f"<title>{xml_escape(p['title'])}</title>"
        f"<link>{SITE_URL}/blog/{p['slug']}/</link>"
        f"<guid>{SITE_URL}/blog/{p['slug']}/</guid>"
        f"<pubDate>{datetime.fromisoformat(p['created_at']).strftime('%a, %d %b %Y %H:%M:%S +0000')}</pubDate>"
        f"<category>{xml_escape(p['category'])}</category>"
        f"</item>"
        for p in posts
    )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0"><channel>'
        "<title>Math Notes</title>"
        f"<link>{SITE_URL}/</link>"
        "<description>Math notes, derivations, and worked word problems, with real LaTeX.</description>"
        f"{items}"
        "</channel></rss>"
    )
    return Response(content=xml, media_type="application/rss+xml")
