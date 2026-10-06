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
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
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

def _preview_plots_dir():
    """Scratch output for the admin editor's explicit "Generate graph" action
    (render_plots.process_live) -- deliberately separate from db.PLOTS_DIR (the real
    directory create_post()/update_post() write to), so clicking it while experimenting,
    then abandoning the edit without saving the post, can never change what a live,
    already-published post's graph looks like. Computed fresh on every call, not cached
    as a module constant -- db.PLOTS_DIR is itself a plain mutable module attribute
    (tests monkeypatch it directly), and caching this once at import time would silently
    keep pointing at the real default forever after, regardless of what db.PLOTS_DIR
    later became.
    """
    return db.PLOTS_DIR.parent / "preview_plots"

_home_html = None
_home_toc = None
_latex_guide_html = None
_latex_guide_toc = None
_matplotlib_quickref_html = None
_matplotlib_quickref_toc = None
_matplotlib_guide_html = None
_matplotlib_guide_toc = None


@asynccontextmanager
async def lifespan(app):
    global _home_html, _home_toc, _latex_guide_html, _latex_guide_toc
    global _matplotlib_quickref_html, _matplotlib_quickref_toc, _matplotlib_guide_html, _matplotlib_guide_toc
    db.init_db()
    _home_html, _home_toc = render.render_markdown((CONTENT_DIR / "index.md").read_text(encoding="utf-8"))
    _latex_guide_html, _latex_guide_toc = render.render_markdown(
        (CONTENT_DIR / "latex_guide.md").read_text(encoding="utf-8")
    )
    # Same source content, two homes: a compact tab in the admin editor's side panel
    # (no heading of its own -- it already sits under a "Matplotlib" tab label, and the
    # panel is too narrow to spare the space) and this full public page (which, like
    # every other top-level page, needs a real, single H1 for its own title and for
    # secondary_toc to correctly treat the rest as nested under it). The public version's
    # H1 is prepended here, once, rather than written into the shared .md file itself, so
    # the admin panel's copy stays exactly as compact as it already was.
    #
    # The admin copy's own toc_tokens (every ## heading, with no H1 wrapping them) is kept
    # too, for a small Jump to: list at the top of that side panel -- secondary_toc's
    # "more than one top-level heading" fallback returns this flat list completely
    # unchanged, so it needs no special-casing to work here.
    _matplotlib_quickref_html, _matplotlib_quickref_toc = render.render_markdown(
        (CONTENT_DIR / "matplotlib_quickref.md").read_text(encoding="utf-8")
    )
    _matplotlib_guide_html, _matplotlib_guide_toc = render.render_markdown(
        "# Matplotlib Guide\n\n" + (CONTENT_DIR / "matplotlib_quickref.md").read_text(encoding="utf-8")
    )
    yield


app = FastAPI(title="Math Notes", lifespan=lifespan)
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
# Appended as ?v=... to this app's own /javascripts and /stylesheets URLs. Those are served
# with only an ETag/Last-Modified, which browsers are allowed to cache heuristically without
# revalidating -- so after a deploy a visitor could keep running the previous script
# (reported live: a fix "still" not working). A new value per process start means every
# redeploy changes the URL and forces a fresh fetch.
templates.env.globals["asset_v"] = str(int(time.time()))

app.mount("/javascripts", StaticFiles(directory=str(BASE_DIR / "static" / "javascripts")), name="javascripts")
app.mount("/stylesheets", StaticFiles(directory=str(BASE_DIR / "static" / "stylesheets")), name="stylesheets")

NAV_ITEMS = [
    ("home", "Home", "/"),
    ("blog", "Blog", "/blog/"),
    ("latex-guide", "LaTeX Guide", "/latex-guide/"),
    ("matplotlib-guide", "Matplotlib Guide", "/matplotlib-guide/"),
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
        "all_tags": db.list_tags(),
        "is_admin": is_admin,
        "extra_sidebar_links": [],
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


def _render_segment_preview(text, slug=None):
    """The admin editor's per-block view-mode content -- a real render of exactly what's
    currently typed for this one block (not necessarily saved yet), so switching a block
    to view mode reflects in-progress edits, not just the last save. Uses
    render_plots.process_preview (never executes a matplotlib block's code -- see that
    function's docstring) rather than render_plots.process, since this runs on every
    edit<->view toggle, not just on save.

    slug must match whatever db._render() used for this post's *last real save*
    (db.PLOTS_DIR/<slug>/), since that's the only place an already-saved graph's PNG
    could actually be -- without it, an existing, previously-saved graph would show the
    "will render after you save" placeholder every time, since it'd be looking in the
    wrong directory. A brand new, not-yet-saved post has no real slug yet and therefore
    no graph of its could possibly already exist anywhere, so a placeholder path that
    nothing ever writes to is correct there, not a bug to work around.
    """
    processed = render.normalize_display_math_spacing(text)
    if slug:
        plots_dir = db.PLOTS_DIR / slug
        assets_url_prefix = f"/assets/plots/{slug}"
    else:
        plots_dir = db.PLOTS_DIR / ".unsaved-preview"
        assets_url_prefix = "/assets/plots/.unsaved-preview"
    processed = render_plots.process_preview(processed, plots_dir, assets_url_prefix=assets_url_prefix)
    html, _ = render.render_markdown(processed)
    return render.expand_details_blocks(html)


def _generate_graph_preview(text):
    """The admin editor's explicit "Generate graph" action -- unlike
    _render_segment_preview, this genuinely executes the block's matplotlib code
    (render_plots.process_live), into _preview_plots_dir(), never the real db.PLOTS_DIR a
    save writes to. A broken block is expected here (that's the point of a button the
    author clicks on purpose to check whether their in-progress code works), so its
    error is shown inline rather than raised.
    """
    try:
        processed = render.normalize_display_math_spacing(text)
        processed = render_plots.process_live(
            processed, _preview_plots_dir(), assets_url_prefix="/admin/preview-plots",
        )
        html, _ = render.render_markdown(processed)
        return render.expand_details_blocks(html)
    except render_plots.PlotError as e:
        return f'<p class="admin-error">{xml_escape(str(e))}</p>'


def _segment_dict(text, slug=None):
    lines = max(text.count("\n") + 1, 1)
    return {
        "text": text,
        "label": render.classify_segment(text) if text.strip() else "Paragraph",
        "rows": min(max(lines + 1, 2), 20),
        "view_html": _render_segment_preview(text, slug) if text.strip() else "",
    }


def _segments_from_draft(draft_segments, slug=None):
    """Same "always at least one block" guarantee _segments_for gives a blank/brand-new
    post -- a draft whose only saved state was, say, a title typed before anything else
    still needs one empty textarea to land the cursor in, not an empty list.
    """
    texts = draft_segments or [""]
    return [_segment_dict(t, slug) for t in texts]


def _segments_for(body_markdown, slug=None):
    """The admin editor's per-block view of a post's body -- a Gutenberg-style editor
    over the same flat body_markdown, not a new content model (see render.py's
    split_into_segments/join_segments). A brand new post starts with a single empty
    paragraph block rather than an empty list, so the form always has at least one
    textarea to type into. slug is the post's own (existing posts only) -- see
    _render_segment_preview for why it's needed to correctly preview an already-saved
    matplotlib block.
    """
    texts = render.split_into_segments(body_markdown) if body_markdown else []
    if not texts:
        texts = [""]
    return [_segment_dict(t, slug) for t in texts]


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


def _relative_time(iso_string):
    """"2 minutes ago" / "just now" for the admin editor's "restored a draft" banner --
    the exact save time matters far less there than how stale the recovered content
    might be, which a relative phrase conveys at a glance in a way an absolute timestamp
    doesn't.
    """
    delta = datetime.now(timezone.utc) - datetime.fromisoformat(iso_string)
    seconds = int(delta.total_seconds())
    if seconds < 60:
        return "just now"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    days = hours // 24
    return f"{days} day{'s' if days != 1 else ''} ago"


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


def _topic_slug(value):
    """How every category/tag link in the templates builds its URL (see base.html's
    categories panel, post.html, blog_index.html) -- a multi-word value like "constant
    acceleration" becomes "constant-acceleration", not something with a raw space that'd
    only work by accident of browser percent-encoding. Route handlers below match an
    incoming path segment against this, not a plain .lower(), so a category/tag with
    spaces in it actually resolves instead of 404ing-by-empty-list.
    """
    return value.lower().replace(" ", "-")


@app.get("/blog/category/{category}/")
def blog_category(request: Request, category: str):
    all_categories = db.list_categories()
    matched = next((c for c in all_categories if _topic_slug(c) == category.lower()), None)
    posts = [_with_display_date(p) for p in db.list_posts(category=matched)] if matched else []
    heading = matched or category
    ctx = _base_context(request, "blog", heading, f"{heading} - Math Notes")
    ctx.update({"heading": heading, "posts": posts, "category": matched or category})
    return templates.TemplateResponse(request, "blog_index.html", ctx)


@app.get("/blog/tag/{tag}/")
def blog_tag(request: Request, tag: str):
    all_tags = db.list_tags()
    matched = next((t for t in all_tags if _topic_slug(t) == tag.lower()), None)
    posts = [_with_display_date(p) for p in db.list_posts(tag=matched)] if matched else []
    heading = matched or tag
    ctx = _base_context(request, "blog", heading, f"{heading} - Math Notes")
    ctx.update({"heading": heading, "posts": posts, "category": None, "tag": matched or tag})
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
        # Cheap enough to just check the already-rendered HTML rather than re-parsing the
        # post's markdown -- only shown at all when there's at least one graph/diagram to
        # expand, same reasoning as show_matplotlib_help elsewhere in this file.
        "has_graphs": 'class="plot-widget' in post["body_html"],
    })
    return templates.TemplateResponse(request, "post.html", ctx)


@app.get("/latex-guide/")
def latex_guide(request: Request):
    ctx = _base_context(request, "latex-guide", "LaTeX Guide", "LaTeX Guide - Math Notes")
    ctx.update({"content_html": _latex_guide_html, "toc_tokens": render.secondary_toc(_latex_guide_toc)})
    return templates.TemplateResponse(request, "simple_page.html", ctx)


@app.get("/matplotlib-guide/")
def matplotlib_guide(request: Request):
    ctx = _base_context(request, "matplotlib-guide", "Matplotlib Guide", "Matplotlib Guide - Math Notes")
    ctx.update({"content_html": _matplotlib_guide_html, "toc_tokens": render.secondary_toc(_matplotlib_guide_toc)})
    return templates.TemplateResponse(request, "simple_page.html", ctx)


@app.get("/assets/plots/{slug}/{filename}")
def plot_image(slug: str, filename: str):
    post_plots_dir = db.PLOTS_DIR / slug
    path = post_plots_dir / filename
    if not path.is_file() or path.resolve().parent != post_plots_dir.resolve():
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
    return JSONResponse(search.build_index(_home_html, _latex_guide_html, _matplotlib_guide_html, posts))


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
        + "".join(f"<category>{xml_escape(t)}</category>" for t in p["tags"])
        + f"</item>"
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


@app.post("/admin/preview-segment")
def admin_preview_segment(text: str = Form(""), slug: str = Form("")):
    """Called by static/javascripts/admin-blocks.js every time a block is switched from
    edit mode back to view mode -- renders exactly what's currently typed in that one
    block's textarea, saving nothing. Stateless; doesn't touch the database.

    slug (the post being edited, blank for a brand new one) must be passed through so an
    already-saved matplotlib block's preview looks in the right place -- see
    _render_segment_preview.
    """
    return Response(
        content=_render_segment_preview(text, slug or None) if text.strip() else "", media_type="text/html",
    )


@app.post("/admin/generate-graph")
def admin_generate_graph(text: str = Form("")):
    """Called by static/javascripts/admin-blocks.js's "Generate graph" button --
    genuinely executes the block's matplotlib code (unlike preview-segment above), into
    _preview_plots_dir(), never the real path a save writes to. Doesn't touch the database.
    """
    return Response(content=_generate_graph_preview(text) if text.strip() else "", media_type="text/html")


@app.get("/admin/preview-plots/{filename}")
def admin_preview_plot_image(filename: str):
    preview_plots_dir = _preview_plots_dir()
    path = preview_plots_dir / filename
    if not path.is_file() or path.resolve().parent != preview_plots_dir.resolve():
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(path, media_type="image/png")


@app.post("/admin/draft")
def admin_save_draft(
    key: str = Form(...),
    title: str = Form(""),
    category: str = Form(""),
    tags: str = Form(""),
    segments: list[str] = Form(default=[]),
):
    """Called every couple of minutes by static/javascripts/admin-autosave.js -- saves
    whatever's currently typed into a `drafts` row keyed by `key` (never `posts`, see
    db.save_draft), so it can't collide with -- let alone silently overwrite -- a real
    save, and never executes a matplotlib block's code as a side effect of just sitting
    in the editor (db.save_draft stores `segments` as-is; nothing here calls render_plots
    at all).

    `key` is only ever "post:<id>" or "new:<token>" from admin_form.html's own hidden
    field (see admin_new_form/admin_edit_form below) -- not a real access-control
    boundary (this whole prefix is already behind Caddy's basic_auth), just cheap enough
    sanity-checking that a malformed key can't silently create a draft nothing will ever
    look up again.
    """
    if not (key.startswith("post:") or key.startswith("new:")):
        raise HTTPException(status_code=400, detail="invalid draft key")
    saved_at = db.save_draft(key, title, category, tags, segments)
    return JSONResponse({"saved_at": saved_at})


@app.get("/admin/")
def admin_list(request: Request):
    return _set_admin_cookie(templates.TemplateResponse(
        request, "admin_list.html", _admin_context(request, "Posts", posts=db.list_posts(), error=None),
    ))


@app.get("/admin/new")
def admin_new_form(request: Request):
    # The draft token lives in the URL itself (not just a hidden form field) specifically
    # so the *same* in-progress new post can be found again -- via browser history/back,
    # a bookmark, or just reloading -- rather than every fresh GET /admin/new silently
    # starting a new, disconnected draft lineage. A bare /admin/new (no token yet, e.g.
    # the "+ New post" nav link) mints one and redirects once, so the token is in the
    # address bar from the very first real page view onward.
    token = request.query_params.get("draft")
    if not token:
        return RedirectResponse(f"/admin/new?draft={uuid4().hex}", status_code=303)
    draft_key = f"new:{token}"

    if request.query_params.get("discard_draft") == "1":
        db.delete_draft(draft_key)

    draft = db.get_draft(draft_key)
    post = None
    segments = _segments_for("")
    draft_restored_at = None
    if draft:
        post = {
            "title": draft["title"], "category": draft["category"],
            "tags": [t.strip() for t in draft["tags"].split(",") if t.strip()],
        }
        segments = _segments_from_draft(draft["segments"])
        draft_restored_at = _relative_time(draft["updated_at"])

    return _set_admin_cookie(templates.TemplateResponse(
        request, "admin_form.html",
        _admin_context(
            request, "New post", action=f"/admin/new?draft={token}", post=post, segments=segments, error=None,
            show_all_posts_header_link=False, show_matplotlib_help=True,
            matplotlib_help_html=_matplotlib_quickref_html,
            matplotlib_help_toc=render.secondary_toc(_matplotlib_quickref_toc),
            draft_key=draft_key, draft_restored_at=draft_restored_at,
            discard_draft_href=f"/admin/new?draft={token}&discard_draft=1",
        ),
    ))


@app.post("/admin/new")
def admin_new_submit(
    request: Request,
    title: str = Form(...),
    category: str = Form(...),
    tags: str = Form(""),
    segments: list[str] = Form(...),
    slug: str = Form(""),
    draft_key: str = Form(""),
):
    body_markdown = render.join_segments(segments)
    try:
        db.create_post(title.strip(), category.strip(), body_markdown, tags=tags, slug=slug.strip() or None)
    except (db.DuplicateSlugError, render_plots.PlotError) as e:
        return templates.TemplateResponse(
            request, "admin_form.html",
            _admin_context(
                request, "New post", action="/admin/new", error=str(e),
                post={"title": title, "category": category, "tags": [t.strip() for t in tags.split(",") if t.strip()]},
                segments=[_segment_dict(s) for s in segments],
                show_all_posts_header_link=False, show_matplotlib_help=True,
                matplotlib_help_html=_matplotlib_quickref_html,
                matplotlib_help_toc=render.secondary_toc(_matplotlib_quickref_toc),
                draft_key=draft_key,
            ),
            status_code=422,
        )
    # The draft (if any -- a post created so fast there was never a 2-minute autosave
    # tick has none) is now strictly older than what was just actually saved, so there is
    # never anything useful left for it to recover; leaving it behind would just mean a
    # stale "restore draft?" banner resurfacing on some *future* unrelated new post if
    # its token were ever somehow reused.
    if draft_key:
        db.delete_draft(draft_key)
    return RedirectResponse("/admin/", status_code=303)


@app.get("/admin/{post_id}")
def admin_view(request: Request, post_id: int):
    post = db.get_post(post_id=post_id)
    if not post:
        raise HTTPException(status_code=404, detail="no such post")
    saved = request.query_params.get("saved") == "1"
    ctx = _admin_context(request, post["title"], post=post, saved=saved, show_all_posts_header_link=False)
    ctx["extra_sidebar_links"] = [{"label": "All posts", "href": "/admin/"}]
    return _set_admin_cookie(templates.TemplateResponse(request, "admin_view.html", ctx))


@app.get("/admin/{post_id}/edit")
def admin_edit_form(request: Request, post_id: int):
    post = db.get_post(post_id=post_id)
    if not post:
        raise HTTPException(status_code=404, detail="no such post")

    # Keyed by the post's own id, not a minted token -- unlike a new post (see
    # admin_new_form), an existing post's edit URL is already stable on its own, so
    # there's no equivalent need to round-trip a token through it first.
    draft_key = f"post:{post_id}"
    if request.query_params.get("discard_draft") == "1":
        db.delete_draft(draft_key)

    draft = db.get_draft(draft_key)
    segments = _segments_for(post["body_markdown"], slug=post["slug"])
    draft_restored_at = None
    if draft:
        post = dict(post)
        post["title"] = draft["title"]
        post["category"] = draft["category"]
        post["tags"] = [t.strip() for t in draft["tags"].split(",") if t.strip()]
        segments = _segments_from_draft(draft["segments"], slug=post["slug"])
        draft_restored_at = _relative_time(draft["updated_at"])

    return _set_admin_cookie(templates.TemplateResponse(
        request, "admin_form.html",
        _admin_context(
            request, f"Edit: {post['title']}", action=f"/admin/{post_id}/edit", post=post,
            segments=segments, error=None,
            show_all_posts_header_link=False, show_matplotlib_help=True,
            matplotlib_help_html=_matplotlib_quickref_html,
            matplotlib_help_toc=render.secondary_toc(_matplotlib_quickref_toc),
            draft_key=draft_key, draft_restored_at=draft_restored_at,
            discard_draft_href=f"/admin/{post_id}/edit?discard_draft=1",
        ),
    ))


@app.post("/admin/{post_id}/edit")
def admin_edit_submit(
    request: Request,
    post_id: int,
    title: str = Form(...),
    category: str = Form(...),
    tags: str = Form(""),
    segments: list[str] = Form(...),
    draft_key: str = Form(""),
):
    body_markdown = render.join_segments(segments)
    try:
        db.update_post(post_id, title=title.strip(), category=category.strip(), body_markdown=body_markdown, tags=tags)
    except db.PostNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except render_plots.PlotError as e:
        existing = db.get_post(post_id=post_id)
        return templates.TemplateResponse(
            request, "admin_form.html",
            _admin_context(
                request, "Edit post", action=f"/admin/{post_id}/edit", error=str(e),
                post={"title": title, "category": category, "tags": [t.strip() for t in tags.split(",") if t.strip()]},
                segments=[_segment_dict(s, existing["slug"]) for s in segments],
                show_all_posts_header_link=False, show_matplotlib_help=True,
                matplotlib_help_html=_matplotlib_quickref_html,
                matplotlib_help_toc=render.secondary_toc(_matplotlib_quickref_toc),
                draft_key=draft_key,
            ),
            status_code=422,
        )
    # The real save that was just made is strictly newer than any autosaved draft could
    # be -- nothing left for it to usefully recover, and leaving it behind would just
    # resurface a stale "restore draft?" banner the next time this same post is edited.
    if draft_key:
        db.delete_draft(draft_key)
    # Switch to view mode instead of the listing -- editing an existing post is a "keep
    # iterating on this one" workflow, not "go manage the whole list", so landing back on
    # a rendered view of exactly what was just saved (with a quick way back into Edit)
    # avoids a detour through the list on every single save.
    return RedirectResponse(f"/admin/{post_id}?saved=1", status_code=303)


@app.post("/admin/{post_id}/delete")
def admin_delete(post_id: int):
    if not db.get_post(post_id=post_id):
        raise HTTPException(status_code=404, detail="no such post")
    db.delete_post(post_id)
    return RedirectResponse("/admin/", status_code=303)
