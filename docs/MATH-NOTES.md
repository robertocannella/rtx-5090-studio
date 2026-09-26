# Math Notes

A public math/physics blog at **`math.example.com`** -- personal notes,
derivations, and worked word problems, written in Markdown with real LaTeX math. Unlike
everything else in this doc set, this one is meant to be read by other people, not just
as an operator reference.

## Architecture: two small FastAPI services sharing one SQLite database

```text
Browser (math.example.com)          Configuration UI (generator.example.com)
  |                                            |  "Math Notes" tab
Caddy (no basic_auth -- public)             Caddy (basic_auth)
  |                                            |
edge                                        history-ui
  |                                            |
math-notes (public, read-only)              mathnotes_internal
  |                                            |
  +-------------- shared ./data --------------math-notes-api (private, read/write)
```

- **`math-notes`** -- public, read-only. Serves the blog, category pages, the LaTeX
  guide, and the RSS feed. Joins only `edge`.
- **`math-notes-api`** -- private post management (create/update/delete/list). Joins
  only `mathnotes_internal`, a private Docker network shared with `history-ui` -- never
  reachable from the public internet. `history-ui`'s Configuration UI (a "Math Notes"
  tab, see below) is the only client, gated the same way that whole UI is (Caddy
  `basic_auth` on `generator.example.com` -- see the note on that below).
- Both are the **same Docker image** (`math-notes:local`, built from one `Dockerfile`),
  just started with a different `uvicorn` target (`public_app:app` vs `admin_app:app`,
  see `compose.yaml`'s two service definitions) and different networks.
- Both share the same SQLite database file and plot-image directory via a bind-mounted
  `./data` volume (`math-notes.db`, `assets/plots/*.png`) -- a write from `math-notes-api`
  is immediately visible to `math-notes`'s next read, no HTTP call between the two
  services at all.

## Why this replaced a static MkDocs build

This site used to be a static site built with MkDocs Material -- chosen originally over
WordPress specifically because it needed no database, no PHP, and no admin login surface
to secure (see git history for that reasoning). It was rebuilt into this dynamic
database-backed pair of services because the actual requirement changed: **posts needed
to be created from a web UI, not by editing Markdown files by hand**, and that content
needed to live in a real database rather than git-tracked files.

The good news: almost none of the actual *content* logic had to change. LaTeX rendering,
word-problem admonitions, and matplotlib graphs are all built on the same underlying
Python libraries (Python-Markdown + its extensions, and matplotlib itself) whether they
run once at build time (the old way) or once per post-save (the new way) -- see
"Rendering pipeline" below for exactly what moved and what didn't.

## Rendering pipeline: once at save time, never per page view

A post's Markdown is converted to HTML **exactly once**, when it's created or updated
(`src/db.py:create_post()`/`update_post()`) -- every page view after that is a plain
SQLite row fetch (`body_html`/`excerpt_html` columns, already rendered), not a per-request
Markdown parse. This is the same "expensive work happens once, reads are cheap" principle
`history-generator`'s whole pipeline is built around, just applied to a blog post instead
of a video segment.

**Markdown extensions** (`src/render.py`): `admonition` (`!!!` blocks), `pymdownx.details`
(`???` collapsible blocks), `pymdownx.superfences`, `attr_list`, `md_in_html` (lets
`render_plots.py`'s raw HTML `<div>` output pass through untouched), `pymdownx.arithmatex`
in `generic` mode, and `tables`. These are the *exact same* extensions the old MkDocs
build used -- moving from a static build to a dynamic app didn't require reimplementing
any of this, just calling `markdown.markdown(text, extensions=[...])` directly instead of
letting MkDocs' own build pipeline call it.

**LaTeX**: `pymdownx.arithmatex` wraps `$...$`/`$$...$$` math in `<span>`/`<div
class="arithmatex">` markers and normalizes the delimiters to `\(...\)`/`\[...\]` -- it
does **not** render the math itself. That still happens client-side, in the reader's
browser, via [KaTeX](https://katex.org/) (`src/static/javascripts/katex.js`). Since this
is now a plain multi-page site (no more MkDocs' instant-navigation SPA behavior), that
script is just `renderMathInElement(document.body, {...})` at the top level -- loaded
with `defer` after the KaTeX CDN scripts (also `defer`, so all three run in document
order after the page is parsed) -- no `DOMContentLoaded` listener or SPA-navigation
re-wiring needed, which the old MkDocs-based version required.

**Matplotlib graphs** (`src/render_plots.py`): a fenced `` ```matplotlib name="..."
title="..." `` block is executed once, at save time, and replaced with a "Show graph"
button + hidden modal containing the rendered PNG -- the image is never shown inline,
only on demand. This is the dynamic-app adaptation of the original MkDocs-build-time
version: that one scanned `.md` files on disk as a Docker build step; this one processes
a single Markdown string, called directly from `db.py` whenever a post is saved. A
mistake in the plotting code (a typo, a `name` reused by two different graphs, code that
never actually calls a plotting function) raises `render_plots.PlotError`, which
`admin_app.py` turns into a `422` with a message naming the broken block -- the save
fails loudly, rather than silently publishing a broken page. The popup itself
(`src/static/javascripts/plot-modal.js`) uses plain event delegation on `document`,
attached once -- this never needed to change, since a plain multi-page site never had the
SPA-navigation duplicate-listener hazard the old categories sidebar (on the previous
MkDocs build) once had.

**Categories sidebar**: a small, collapsed-by-default panel on the right edge of every
page, listing every category in use, each linking to its `/blog/category/<name>/`
archive. This got *simpler* moving to a dynamic app -- the old MkDocs version needed a
build-time hook (`hooks.py`) to scan every post's frontmatter for its category, since
MkDocs had no live database to query. Here, `db.list_categories()` is just `SELECT
DISTINCT category FROM posts`, run fresh on every page render
(`public_app.py`'s routes all pass `categories=db.list_categories()` into their template
context) -- no separate build-time scanning step exists at all anymore.

## Database schema

One table, `posts` (`src/db.py:init_db()`):

| Column | Purpose |
|---|---|
| `id` | Primary key, used by the admin API's URLs (`/posts/{id}`) |
| `slug` | Permanent URL segment (`/blog/{slug}/`) -- unique, immutable after creation (see below) |
| `title`, `category` | Shown as-is |
| `body_markdown` | The author's original Markdown, kept so a post can be re-edited |
| `body_html`, `excerpt_html` | Pre-rendered HTML (see "Rendering pipeline" above) -- `excerpt_html` is everything before a `<!-- more -->` marker (or the whole post, if there's no marker), same convention the old MkDocs blog plugin used |
| `created_at`, `updated_at` | ISO 8601 UTC timestamps |

`journal_mode=WAL` (`db.py:get_connection()`) lets the public app's reads proceed without
blocking on the admin app's occasional writes (and vice versa) -- the two are separate OS
processes in separate containers, not threads in one process, so a plain rollback-journal
SQLite database would otherwise serialize more aggressively than this low-write-volume
use case needs.

**Slugs are immutable once a post is created** -- `admin_app.py`'s `UpdatePostRequest`
has no `slug` field at all. The Configuration UI's editor hides the slug field entirely
once you're editing an existing post (rather than showing an input that would silently do
nothing), to make this obvious rather than surprising.

## Creating and managing posts

**From the Configuration UI** (`generator.example.com`, "Math Notes" tab) --
click "New post", fill in title/category/body (Markdown, same LaTeX/admonition/matplotlib
syntax as always -- see the live [LaTeX Guide](https://math.example.com/latex-guide/)),
click "Save post". The post is live **immediately** -- there's no build or deploy step
between saving and it appearing on the public site, unlike the old MkDocs version, which
needed a `docker compose up -d --build` after every content change.

`app.js`'s Math Notes tab (`loadMathNotesPosts()`, `startNewMathNotesPost()`,
`startEditMathNotesPost()`, `saveMathNotesPost()`, `deleteMathNotesPost()`) talks to
`history-ui`'s own new proxy routes (`ui/main.py`, `/api/math-notes/*`), which forward to
`math-notes-api` over `mathnotes_internal` -- the same thin-proxy pattern already used for
every other route in that UI (see [Configuration UI](#configuration-ui) above). Deleting
a post reuses the same generic confirm-modal pattern already built for deleting episodes
(`openConfirmModal()`).

**A real security fix made alongside this feature**: `generator.example.com` had
**no `basic_auth` at all** in the live Caddyfile before this -- the whole Configuration
UI (episode delete, YouTube publish, and now post authoring) was reachable by anyone who
knew the URL, despite `docs/README.md`'s service table claiming otherwise. Fixed by
adding the same `basic_auth` block `docs.example.com` already uses. Embedding the
Math Notes authoring UI as a *new tab in an already-public* Configuration UI would have
made post-authoring public too, had this not been caught and fixed first.

## Deploying a change

Both services share one image -- rebuild once, redeploy both:

```bash
cd /srv/apps/math-notes
docker compose up -d --build
```

Neither service holds any in-flight state worth protecting (all real state is in
`./data`, on the shared bind mount, untouched by a container recreate) -- unlike
`history-api`, there's no "check for an active job first" concern here.

## Local preview and tests

```bash
cd /srv/apps/math-notes
docker build -t math-notes:local .
docker run --rm -v "$PWD/tests:/app/tests" -w /app/src math-notes:local \
  sh -c "pip install --quiet pytest httpx && python -m pytest ../tests -q"
```

**Tests**: `tests/test_render.py` (Markdown extensions, admonitions, arithmatex,
excerpt-splitting), `tests/test_render_plots.py` (matplotlib block execution, error
handling for broken/empty plotting code), `tests/test_db.py` (post CRUD, slug
uniqueness/generation, the `created_at` override migration relies on), `tests/test_public_app.py`
(every public route, including a real matplotlib-post render + image fetch), and
`tests/test_admin_app.py` (every admin route, including validation and the `409`/`404`/`422`
error-status mapping). A `tests/conftest.py` sets `MATH_NOTES_DB_PATH`/`MATH_NOTES_PLOTS_DIR`
env vars *before* any app module is imported, since `public_app.py`'s static-file mount
for served images captures its directory once, at import time -- a `monkeypatch` applied
after import can't retroactively change it, which is exactly the bug this conftest setup
works around (found live, fixed before it ever reached production).

## Migrating existing posts

`migrate_posts.py` (app root, not part of the running image) is a one-time tool that
reads the original Markdown files this site used to be built from (`docs/blog/posts/*.md`
-- kept in the repo purely as a historical record now, not read by anything at runtime)
and inserts them as database rows, preserving each post's original `date:` frontmatter as
its `created_at` (via `db.create_post()`'s optional `created_at` parameter) rather than
resetting every migrated post's date to "now" and scrambling the blog's chronological
order. Safe to re-run -- skips any file whose slug already has a post in the database.
Run once, already done for the 3 posts that existed under the old MkDocs build (Welcome,
Projectile motion: horizontal launch, Constant acceleration: airplane takeoff); shouldn't
need to run again.

## LaTeX Guide

The live **[LaTeX Guide](https://math.example.com/latex-guide/)** page
(`src/latex_guide.md`, rendered by `public_app.py:latex_guide()` the same way a post's
body is rendered, just not database-backed since it's fixed reference documentation, not
a post) covers inline vs. display math, superscript/subscript/fractions/roots with worked
examples, a symbol cheat-sheet, the `!!!`/`???` word-problem pattern, and the
`` ```matplotlib `` graph syntax -- all still accurate; none of that syntax changed when
the site moved off MkDocs.
