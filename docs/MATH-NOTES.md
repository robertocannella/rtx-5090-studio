# Math Notes

A public math blog at **`math.example.com`** -- personal notes, derivations, and
worked word problems, written in Markdown with real LaTeX math. Unlike everything else in
this doc set, this one is meant to be read by other people, not just as an operator
reference.

## Architecture

```text
Browser (math.example.com)
  |
Caddy
  |-- /admin/*  -> basic_auth, same credential pattern as docs.example.com
  |-- everything else -> no auth, public
  |
edge
  |
math-notes (one FastAPI app, uvicorn, port 8000)
  |
/app/data -- SQLite (posts) + generated matplotlib PNGs, bind-mounted, gitignored
```

One container, one process, one app (`src/app.py`) serving both the public site and its
own `/admin/*` authoring UI -- there is no separate database service, no second container,
and no dependency on any other app on this server. `history-generator` was tried as the
home for the authoring UI in an earlier iteration and reverted: a math blog's post editor
has nothing to do with a video generator, and coupling them meant a change to one app's
Configuration UI could break the other's ability to publish a post. Authoring now lives
entirely inside `math-notes` itself, gated by Caddy the same way `docs.example.com`
and `generator.example.com` already are, just scoped to one path prefix instead of
the whole site.

Posts are rendered from the database on every request -- there is no static build step, no
`mkdocs build`, and no Docker rebuild needed to publish a new post. Markdown ->
HTML (`render.py`), matplotlib code-block execution (`render_plots.py`), the table of
contents, and the reading-time estimate are all computed once, at save time (`db.py`'s
`create_post`/`update_post`), not per page view -- a page load is a plain row fetch and a
Jinja2 template render, nothing more expensive than that.

## Why this looks exactly like the old MkDocs site

This app used to be a static [Material for MkDocs](https://squidfunk.github.io/mkdocs-material/)
build. Rebuilding the authoring feature as a from-scratch dynamic app the first time also
replaced Material's real theme with a hand-rolled one, on the reasoning that recreating
Material's whole theme by hand wasn't worth it for a first version -- that was the wrong
call. The hand-rolled theme's colors were worse for actually reading long-form math
content, so this rebuild vendors **Material's own real, compiled CSS and JS** instead
of reinventing them:

- `static/vendor/stylesheets/main.*.min.css` and `palette.*.min.css` -- extracted directly
  from an actual `mkdocs-material` build's output (`docs/HISTORY-GENERATOR.md`-style: read
  the real thing, don't guess), not rewritten. This is exactly why the site's colors,
  spacing, and typography are identical to before.
- `static/vendor/javascripts/bundle.*.min.js` -- Material's real client-side behavior:
  instant-loading navigation, the light/dark palette toggle, the search box, back-to-top,
  and the code-copy button. `templates/base.html` hand-writes the HTML structure Material's
  CSS/JS expect (`md-header`, `md-tabs`, `md-nav`, `md-content`, `data-md-component`
  attributes, the `__config` script, etc.) once per page type, computed from the database
  instead of from files on disk at build time -- the markup is the same shape either way,
  only where the data comes from changed.
- `static/vendor/javascripts/workers/search.*.min.js` + `lunr/` -- Material's real search
  worker. `/search/search_index.json` (`search.py`) rebuilds the index from whatever posts
  exist right now, on every request -- one entry per page rather than per heading (a
  simplification given how few pages this site has), but built from the same `{config,
  docs}` shape the real worker expects, captured from an actual build's output rather than
  invented.

`docs/javascripts/katex.js`, `categories-panel.js`, and `plot-modal.js` (now under
`src/static/javascripts/`) are carried over completely unchanged from the original static
site -- they were already written to work correctly with Material's *real* instant-loading
navigation (see "Categories sidebar" below for exactly why), so nothing about them needed
to change when the rendering moved from build-time to per-request.

## Writing a post

Go to `https://math.example.com/admin/` (prompts for the same basic_auth
credentials as `docs.example.com`), click **New post**, and fill in:

- **Title** -- also becomes the page's `<h1>`.
- **Category** -- freeform text; every distinct category used across all posts
  automatically gets a `/blog/category/<name>/` archive page and shows up in the
  categories sidebar (see below). No separate list to maintain.
- **Slug** (optional, new posts only) -- derived from the title if left blank
  (`db.slugify`). Editing an existing post's title does not change its slug, so existing
  links never break.
- **Body (Markdown)** -- see below for LaTeX, word-problem, and graph syntax. An excerpt
  for the blog index is everything before a `<!-- more -->` marker (or the whole post, if
  there's no marker) -- exactly the same convention the old MkDocs `blog` plugin used, so
  existing posts needed no rewriting when this moved to the database.

Saving re-renders the post immediately -- no build step, no waiting. A mistake in a
matplotlib block (see below) is reported right there on the form and the post is not
saved, rather than silently shipping a broken page.

**LaTeX**: inline math is `$...$`, display math is a `$$ ... $$` or `\[ ... \]` block on
its own lines, exactly like writing real LaTeX. This is `pymdownx.arithmatex`
(`generic: true`) wrapping the math in spans/divs that `static/javascripts/katex.js` finds
and renders via KaTeX after each page load -- including Material's instant-navigation page
swaps (`document$.subscribe`, not a plain `DOMContentLoaded` listener, is what makes math
still render on a page reached without a full reload).

A display-math block only gets recognized when its markers are isolated from surrounding
text by a blank line -- that's Markdown's normal rule for any block-level construct, not
special to math, but content pasted straight from ChatGPT (which writes `\[ ... \]`
immediately butted up against the surrounding prose, no blank line at all) never follows
it. `render.normalize_display_math_spacing()` inserts the missing blank line automatically
at save time, so pasting ChatGPT's own math formatting in verbatim just works -- see that
function's docstring for exactly why the un-isolated form silently renders as literal `[x]`
text instead of math (core Markdown's backslash-escape handling wins the race against
arithmatex's block processor when the block isn't isolated).

**Word problems**: state the problem in a `!!! question "Problem"` admonition, then the
answer in a `??? success "Solution"` block -- the `???` (vs `!!!`) makes it collapsed by
default, so a reader can attempt the problem before revealing the answer.

**A live, in-depth reference for all of this** is `math.example.com/latex-guide/`
itself (source: `src/content/latex_guide.md`) -- inline vs. display math,
superscript/subscript/fractions/roots with worked examples, a symbol cheat-sheet, and the
word-problem and graph syntax in full.

## Navigation

The three tabs across the top of every page (Home, Blog, LaTeX Guide) are a plain list in
`app.py` (`NAV_ITEMS`), looped over once in `templates/base.html` to render both the top
tab bar and the primary sidebar's nav tree -- adding a new non-blog page means adding an
entry there and a route; blog posts and categories need neither, both are already
data-driven from whatever exists in the database.

### Categories sidebar

A small, custom, collapsed-by-default panel pinned to the right edge of every page,
listing every distinct category across all posts (`db.list_categories()`, passed into
every template as `all_categories`), each linking to its `/blog/category/<name>/` archive
page. Material has no built-in widget for this -- it's two pieces, both carried over
unchanged from the original static site:

- The panel's markup, rendered directly in `templates/base.html` (not a Jinja block
  override anymore -- there's no separate Material base template to extend now that this
  app owns its own `base.html` outright).
- `static/javascripts/categories-panel.js` -- the click-to-toggle behavior, via plain
  event delegation on `document`, not `document$.subscribe`.

**Why event delegation on `document`, not `document$.subscribe`**: an earlier version of
this script re-queried the toggle button and attached a fresh click listener inside
`document$.subscribe`, on the assumption that Material's instant navigation replaces the
panel's DOM on every page swap the same way it replaces the main content area. It doesn't:
the panel sits outside the region instant navigation actually swaps, so the button's DOM
node persists unchanged across every navigation. `document$.subscribe` still fired on
every navigation though, and each firing attached a brand-new closure as an *additional*
listener on that same persistent button (a fresh arrow function is never `==` the previous
one, so the browser never deduplicates it) -- so after visiting even one other page, a
single click fired two listeners back to back, which toggled the panel open then
immediately closed again. The net effect: **the button appeared to do nothing at all once
you'd navigated anywhere**, reported live as "the categories sidebar doesn't work when
viewing a post." Plain event delegation on `document`, attached exactly once at
script-load time, fixes this categorically -- `document` itself is never replaced by
instant navigation, so the listener is never re-attached no matter how many pages get
visited, regardless of whether the button's own node persists or gets recreated.
`plot-modal.js` (below) uses this same delegated pattern from the start, so it never had
this bug.

## Matplotlib graphs

A post can embed a real matplotlib figure, shown only on demand in a popup -- e.g. the
trajectory graph in the projectile-motion post, or the position/velocity graphs in the
airplane-takeoff post. matplotlib is Python-only, so there's no way to run it in the
reader's browser -- the figure is rendered to a PNG once, at save time.

**Author-facing syntax**: a fenced code block tagged `matplotlib`, with a required `name`
(used for the image filename and the button's DOM target) and optional `title` (the
button's label):

````markdown
```matplotlib name="projectile-trajectory" title="Show trajectory"
import numpy as np

t = np.linspace(0, 3.03, 100)
x = 10 * t
y = 45 - 0.5 * 9.8 * t**2

fig, ax = plt.subplots()
ax.plot(x, y)
```
````

**`render_plots.py`** (called from `db.py`'s `create_post`/`update_post`, not a build
step) finds every such block via regex, `exec`s its code in a namespace with `plt` already
imported (`matplotlib.use("Agg")` first, since there's no display server in the
container), grabs whatever figure the code produced (`plt.gcf()`), saves it as
`/app/data/assets/plots/<name>.png`, and rewrites the block in the stored Markdown into a
button + hidden `<div class="plot-widget__modal">` containing the image
(`app.py`'s `/assets/plots/{filename}` route serves it back out).

**The popup**: the image is never shown inline -- only a button, so a post's graph doesn't
clutter or spoil anything until a reader deliberately asks for it.
`static/javascripts/plot-modal.js` wires this with plain event delegation on `document`.

**Failure mode**: a mistake in the plotting code (a typo, two graphs reusing the same
`name`, code that never actually calls a plotting function) raises `render_plots.PlotError`,
which the admin form displays as a validation error -- the post is not saved, so there is
never a live page with a broken graph on it.

## Admin visibility on public pages

An "Admin" nav item (next to Home/Blog/LaTeX Guide) and an "Edit post" link in every
post's metadata sidebar only appear once you've visited `/admin/*` -- to an anonymous
visitor, neither exists at all. This is purely cosmetic, not the actual access control:
Caddy's `basic_auth` on `/admin/*` (see `gateway/Caddyfile`) is what actually protects
every admin action, checked independently on every single request to that path prefix,
exactly as it always was.

The wrinkle is that `basic_auth` is scoped to `/admin/*` -- the browser has no reason to
send those credentials on a request to `/`, and this app has no way to see them there
either, so it can't know "is this visitor logged in" on a public page by itself.
`admin_auth.py` bridges that gap with a small signed cookie: every `/admin/*` GET request
that reaches this app has, by construction, already passed Caddy's `basic_auth` (nothing
else can reach this app on that path), so those routes set a cookie
(`admin_auth.make_cookie_value()`, HMAC-signed with `ADMIN_COOKIE_SECRET`) on their
response, scoped site-wide (`Path=/`). Public routes check for it
(`admin_auth.is_valid()`) to decide whether to render the Admin nav item/Edit links.
Forging this cookie would only change what a visitor **sees**, never what they can **do**
-- every real admin action still requires passing Caddy's `basic_auth` independently, so
it doesn't need to be bulletproof, just signed well enough to keep a random visitor from
casually spoofing it.

Requires `ADMIN_COOKIE_SECRET` set in `math-notes/.env` (hand-created on the server, not
committed -- see `.gitignore`'s `**/.env` rule). Without it, the app still runs, but signs
every cookie with an empty key, which is fine for local testing and wrong for production.

## Deploying a code change

Unlike the old static site, deploying here means redeploying the *app*, not rebuilding
content -- content changes (new/edited posts) need no deploy at all, just the admin UI.

```bash
cd /srv/apps/math-notes
docker compose up -d --build
```

## DNS and TLS

`math.example.com` needs an A/CNAME record added in Cloudflare pointing at the
same target as this server's other subdomains -- this isn't something that can be done
from the server itself. Until that record exists, Caddy's automatic HTTPS certificate
request for it will keep failing (`no valid A records found`) and retrying on its own
schedule (`docker logs gateway`); once the record is added, the next retry succeeds
without needing to touch the gateway again.

## Data and backups

`math-notes/data/` (gitignored, not part of any commit) holds `math-notes.db` (the posts)
and `assets/plots/*.png` (generated graph images) -- this is the site's actual content,
the one thing on this host that isn't reproducible from git plus a rebuild. Back it up the
same way any other bind-mounted app data directory on this host is backed up.
