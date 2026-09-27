"""Math Notes -- a single dynamic FastAPI app serving both the public site
(math.example.com/) and its own post-authoring admin UI (math.example.com/admin/*).

Public pages are styled with Material for MkDocs' real, vendored CSS/JS (see
static/vendor/ and templates/base.html) so they look exactly like the site's original
static MkDocs build -- rendering is now per-request from the database (db.py) instead of
a static Docker build step, but nothing about how a page *looks* changed.

/admin/* is a plain server-rendered CRUD UI for posts, gated entirely at the Caddy layer
(basic_auth on that one path prefix, see gateway/Caddyfile) -- this app does no real
authentication of its own, matching every other basic_auth-gated app on this server
(docs.example.com, generator.example.com). See admin_auth.py for the one
exception: a cosmetic "am I logged in" cookie, set on /admin/* responses, that lets public
pages show an Admin nav item and per-post Edit links -- it changes what's shown, never
what's allowed.
"""

import json
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import admin_auth
import db
import render
import render_plots
import search

BASE_DIR = Path(__file__).parent
CONTENT_DIR = BASE_DIR / "content"
SITE_URL = "https://math.example.com"

_home_html = None
_home_toc = None
_latex_guide_html = None
_latex_guide_toc = None


@asynccontextmanager
async def lifespan(app):
    global _home_html, _home_toc, _latex_guide_html, _latex_guide_toc
    db.init_db()
    _home_html, _home_toc = render.render_markdown((CONTENT_DIR / "index.md").read_text(encoding="utf-8"))
    _latex_guide_html, _latex_guide_toc = render.render_markdown(
        (CONTENT_DIR / "latex_guide.md").read_text(encoding="utf-8")
    )
    yield


app = FastAPI(title="Math Notes", lifespan=lifespan)
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

app.mount("/javascripts", StaticFiles(directory=str(BASE_DIR / "static" / "javascripts")), name="javascripts")
app.mount("/stylesheets", StaticFiles(directory=str(BASE_DIR / "static" / "stylesheets")), name="stylesheets")

NAV_ITEMS = [
    ("home", "Home", "/"),
    ("blog", "Blog", "/blog/"),
    ("latex-guide", "LaTeX Guide", "/latex-guide/"),
]


def _nav_tabs(active):
    return [{"label": label, "href": href, "active": key == active} for key, label, href in NAV_ITEMS]


def _base_context(request, active_nav, header_topic, title, is_admin=None):
    # is_admin=None means "figure it out from the cookie" (every public route); admin
    # routes pass is_admin=True explicitly instead, since reaching them at all already
    # proves Caddy validated basic_auth for this exact request, regardless of whether the
    # cookie (set on a *previous* /admin/* response) has propagated yet.
    if is_admin is None:
        is_admin = admin_auth.is_valid(request.cookies.get(admin_auth.COOKIE_NAME))
    return {
        "request": request,
        "site_url": SITE_URL,
        "nav_tabs": _nav_tabs(active_nav),
        "header_topic": header_topic,
        "title": title,
        "toc_tokens": [],
        "primary_sidebar_hidden": False,
        "all_categories": db.list_categories(),
        "is_admin": is_admin,
    }


def _set_admin_cookie(response):
    """Called on every /admin/* GET response -- reaching this app on that path at all
    already proves Caddy validated basic_auth for this request, so it's safe to (re)issue
    this cookie here. See admin_auth.py for what it does and doesn't grant.
    """
    response.set_cookie(
        admin_auth.COOKIE_NAME, admin_auth.make_cookie_value(),
        max_age=admin_auth.MAX_AGE_SECONDS, path="/", secure=True, httponly=True, samesite="lax",
    )
    return response


def _admin_context(request, title, **extra):
    # active_nav="admin" matches none of NAV_ITEMS, so the real site header renders with
    # no tab marked active -- admin isn't Home/Blog/LaTeX Guide, it's a separate surface
    # that happens to share the same chrome.
    ctx = _base_context(request, "admin", title, f"{title} - Math Notes Admin", is_admin=True)
    ctx.update(extra)
    return ctx


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
    ctx = _base_context(request, "home", "Home", "Math Notes")
    ctx.update({"content_html": _home_html, "toc_tokens": render.secondary_toc(_home_toc)})
    return templates.TemplateResponse(request, "simple_page.html", ctx)


@app.get("/blog/")
def blog_index(request: Request):
    posts = [_with_display_date(p) for p in db.list_posts()]
    ctx = _base_context(request, "blog", "Blog", "Blog - Math Notes")
    ctx.update({"heading": "Blog", "posts": posts, "category": None})
    return templates.TemplateResponse(request, "blog_index.html", ctx)


@app.get("/blog/category/{category}/")
def blog_category(request: Request, category: str):
    all_categories = db.list_categories()
    matched = next((c for c in all_categories if c.lower() == category.lower()), None)
    posts = [_with_display_date(p) for p in db.list_posts(category=matched)] if matched else []
    heading = matched or category
    ctx = _base_context(request, "blog", heading, f"{heading} - Math Notes")
    ctx.update({"heading": heading, "posts": posts, "category": matched or category})
    return templates.TemplateResponse(request, "blog_index.html", ctx)


@app.get("/blog/{slug}/")
def blog_post(request: Request, slug: str):
    post = db.get_post(slug=slug)
    if not post:
        raise HTTPException(status_code=404, detail="post not found")
    post = _with_display_date(post)
    ctx = _base_context(request, "blog", post["title"], f"{post['title']} - Math Notes")
    ctx.update({
        "post": post,
        "toc_tokens": render.secondary_toc(json.loads(post["toc_json"])),
        "primary_sidebar_hidden": True,
    })
    return templates.TemplateResponse(request, "post.html", ctx)


@app.get("/latex-guide/")
def latex_guide(request: Request):
    ctx = _base_context(request, "latex-guide", "LaTeX Guide", "LaTeX Guide - Math Notes")
    ctx.update({"content_html": _latex_guide_html, "toc_tokens": render.secondary_toc(_latex_guide_toc)})
    return templates.TemplateResponse(request, "simple_page.html", ctx)


@app.get("/assets/plots/{filename}")
def plot_image(filename: str):
    path = db.PLOTS_DIR / filename
    if not path.is_file() or path.resolve().parent != db.PLOTS_DIR.resolve():
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(path, media_type="image/png")


@app.get("/assets/{path:path}")
def vendor_asset(path: str):
    target = (BASE_DIR / "static" / "vendor" / path).resolve()
    vendor_root = (BASE_DIR / "static" / "vendor").resolve()
    if vendor_root not in target.parents or not target.is_file():
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(target)


@app.get("/search/search_index.json")
def search_index():
    posts = db.list_posts()
    return JSONResponse(search.build_index(_home_html, _latex_guide_html, posts))


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


# ---------------------------------------------------------------------------
# Admin -- CRUD UI for posts. Gated entirely by Caddy's basic_auth on the /admin
# prefix (see gateway/Caddyfile), not by anything in this app.
# ---------------------------------------------------------------------------


@app.get("/admin/")
def admin_list(request: Request):
    return _set_admin_cookie(templates.TemplateResponse(
        request, "admin_list.html", _admin_context(request, "Posts", posts=db.list_posts(), error=None),
    ))


@app.get("/admin/new")
def admin_new_form(request: Request):
    return _set_admin_cookie(templates.TemplateResponse(
        request, "admin_form.html",
        _admin_context(request, "New post", action="/admin/new", post=None, error=None),
    ))


@app.post("/admin/new")
def admin_new_submit(
    request: Request,
    title: str = Form(...),
    category: str = Form(...),
    body_markdown: str = Form(...),
    slug: str = Form(""),
):
    try:
        db.create_post(title.strip(), category.strip(), body_markdown, slug=slug.strip() or None)
    except (db.DuplicateSlugError, render_plots.PlotError) as e:
        return templates.TemplateResponse(
            request, "admin_form.html",
            _admin_context(
                request, "New post", action="/admin/new", error=str(e),
                post={"title": title, "category": category, "body_markdown": body_markdown},
            ),
            status_code=422,
        )
    return RedirectResponse("/admin/", status_code=303)


@app.get("/admin/{post_id}/edit")
def admin_edit_form(request: Request, post_id: int):
    post = db.get_post(post_id=post_id)
    if not post:
        raise HTTPException(status_code=404, detail="no such post")
    return _set_admin_cookie(templates.TemplateResponse(
        request, "admin_form.html",
        _admin_context(request, f"Edit: {post['title']}", action=f"/admin/{post_id}/edit", post=post, error=None),
    ))


@app.post("/admin/{post_id}/edit")
def admin_edit_submit(
    request: Request,
    post_id: int,
    title: str = Form(...),
    category: str = Form(...),
    body_markdown: str = Form(...),
):
    try:
        db.update_post(post_id, title=title.strip(), category=category.strip(), body_markdown=body_markdown)
    except db.PostNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except render_plots.PlotError as e:
        return templates.TemplateResponse(
            request, "admin_form.html",
            _admin_context(
                request, "Edit post", action=f"/admin/{post_id}/edit", error=str(e),
                post={"title": title, "category": category, "body_markdown": body_markdown},
            ),
            status_code=422,
        )
    return RedirectResponse("/admin/", status_code=303)


@app.post("/admin/{post_id}/delete")
def admin_delete(post_id: int):
    if not db.get_post(post_id=post_id):
        raise HTTPException(status_code=404, detail="no such post")
    db.delete_post(post_id)
    return RedirectResponse("/admin/", status_code=303)
