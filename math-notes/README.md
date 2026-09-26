# Math Notes

A public math/physics blog at **https://math.example.com** -- two small FastAPI
services (`public_app.py`, read-only; `admin_app.py`, private post management) sharing
one SQLite database. See `/srv/apps/docs/MATH-NOTES.md` (on `docs.example.com`)
for the full architecture writeup -- this file is the short, practical reference.

## Creating a post

**Use the Configuration UI** (`generator.example.com`, "Math Notes" tab) --
click "New post", fill in title/category/body, save. It's live immediately, no rebuild
needed. This is the only supported way to create a post day to day; there's no file to
hand-edit anymore.

Markdown syntax is unchanged from before:

- `$...$` / `$$...$$` for LaTeX (rendered client-side by KaTeX).
- `!!! question "Problem"` / `??? success "Solution"` for word problems (`???` is
  collapsed by default).
- `` ```matplotlib name="..." title="..." `` for a graph, shown as a "Show graph" popup
  button rather than inline.
- `<!-- more -->` to mark where the blog-index excerpt should cut off.

See the live **[LaTeX Guide](https://math.example.com/latex-guide/)** for the
full syntax reference with worked examples.

## Architecture at a glance

```text
math-notes      (public, read-only, joins `edge`)
math-notes-api  (private post CRUD, joins `mathnotes_internal` -- history-ui only)
```

Both are the same image (`math-notes:local`), started with a different `uvicorn` target
(see `compose.yaml`). Both share `./data` (the SQLite database + generated plot images)
via a bind mount. See `docs/MATH-NOTES.md` for the full diagram and reasoning.

## Deploying a change

```bash
cd /srv/apps/math-notes
docker compose up -d --build
```

Rebuilds and redeploys both services from the one image. No "check for an active job"
concern -- all real state lives in `./data`, untouched by a container recreate.

## Local preview and tests

```bash
cd /srv/apps/math-notes
docker build -t math-notes:local .
docker run --rm -v "$PWD/tests:/app/tests" -w /app/src math-notes:local \
  sh -c "pip install --quiet pytest httpx && python -m pytest ../tests -q"
```

To actually run the app locally against a throwaway database:

```bash
docker run --rm -p 8080:8000 -v /tmp/mn-data:/app/data math-notes:local
# open http://localhost:8080
```

## Source layout

| Path | Purpose |
|---|---|
| `src/public_app.py` | Public routes: home, blog index, post view, category view, RSS, static assets |
| `src/admin_app.py` | Private routes: create/update/delete/list posts, list categories |
| `src/db.py` | SQLite schema and all post CRUD -- both apps import this directly (not an HTTP call between them) |
| `src/render.py` | Markdown -> HTML (the extension config), excerpt-splitting |
| `src/render_plots.py` | Executes `` ```matplotlib `` blocks once at save time, replaces them with a button+popup |
| `src/latex_guide.md` | The live LaTeX Guide page's content (not database-backed -- fixed reference docs) |
| `src/templates/` | Jinja2 templates for the public site (a simple custom theme, not Material for MkDocs) |
| `src/static/` | CSS + the three client-side JS files (KaTeX loader, categories-panel toggle, plot-modal popup) |
| `migrate_posts.py` | One-time tool that imported the original 3 Markdown-file posts into the database -- already run, shouldn't need to run again |
| `docs/` | The original Markdown source files, kept as a historical record only -- nothing at runtime reads this anymore |

## Admonition types (`!!!`/`???`)

The word right after `!!!`/`???` is the admonition **type** and controls its color --
`question` (blue), `info` (light blue), and `success` (green) are the ones actually used
across posts today, styled in `src/static/stylesheets/site.css` (`.admonition.<type>`,
`details.<type>`). To add a new type, add two rules there following that same pattern --
no code changes needed, `admonition`/`pymdownx.details` accept any type name and just
fall back to an unstyled look for one they don't recognize.
