# Math Notes

A public math/physics blog at **https://math.example.com**, with LaTeX rendered
by [KaTeX](https://katex.org/) and Material for MkDocs' real theme (vendored, not
reinvented). See `/srv/apps/docs/MATH-NOTES.md` (on `docs.example.com`) for the
full architecture writeup -- this file is the short, practical "how do I add a post"
reference.

## Posts live in a database now -- write them from the browser

There's no Markdown file to create and no rebuild needed to publish. Go to
**https://math.example.com/admin/** (same basic_auth credentials as
`docs.example.com`), click **New post**, fill in title/category/body, save --
it's live immediately.

- **Category** is freeform text; every distinct value in use automatically gets a
  `/blog/category/<name>/` archive page and shows up in the categories sidebar.
- **Slug** is optional on a new post -- left blank, it's derived from the title. Editing a
  post's title later never changes its existing slug/URL.
- A `<!-- more -->` marker in the body splits "excerpt shown on the index" from "rest of
  the post, only shown on the post's own page" -- put it right after the intro paragraph.

## Writing math and word problems

See the live **[LaTeX Guide](https://math.example.com/latex-guide/)**
(`src/content/latex_guide.md`) -- inline vs. display math, a cheat-sheet of common LaTeX
syntax, and the `!!! question` / `??? success` problem/solution pattern used throughout
the posts here.

Pasting math straight out of ChatGPT (which writes `\[ ... \]` with no blank line around
it) works as-is -- saving a post automatically fixes the spacing display math needs to be
recognized (`render.normalize_display_math_spacing`), same as `$$ ... $$`.

## Admin nav item and Edit links only show once you've logged in

The "Admin" tab and each post's "Edit post" link are hidden from anonymous visitors --
they appear after your first visit to `/admin/` in that browser (see
`/srv/apps/docs/MATH-NOTES.md`'s "Admin visibility on public pages" for how). The real
protection on `/admin/*` is still Caddy's `basic_auth`, unaffected by any of this.

## Adding a graph

Write a fenced ` ```matplotlib name="..." ` code block in a post's body -- saving the post
executes it (`render_plots.py`), saves the figure as a PNG, and replaces the block with a
button that pops the image open in a modal. See the live
**[LaTeX Guide](https://math.example.com/latex-guide/)**'s "Adding a graph"
section for the exact syntax and a full example. A mistake in the plotting code is
reported right on the admin save form -- the post isn't saved until it's fixed.

## Adding a non-blog page (Home, LaTeX Guide)

These are plain Markdown files under `src/content/`, rendered once at app startup, listed
in `app.py`'s `NAV_ITEMS` (which drives both the top tab bar and the primary sidebar) --
add the file, add a route in `app.py`, add an entry to `NAV_ITEMS`.

## Categories sidebar

A small, collapsed-by-default panel on the right edge of every page lists every category
in use, linking to its `/blog/category/<name>/` archive -- fully data-driven from
`db.list_categories()`, nothing to maintain by hand. See `templates/base.html` for the
markup and `static/javascripts/categories-panel.js` for the toggle behavior; see
`/srv/apps/docs/MATH-NOTES.md` for why that script uses plain event delegation instead of
Material's `document$.subscribe`.

## Deploying a code change

Content changes (posts) need no deploy at all -- only a change to the app's own code does:

```bash
cd /srv/apps/math-notes
docker compose up -d --build
```

## Running the tests

```bash
cd /srv/apps/math-notes
docker run --rm -v "$(pwd)":/app -w /app python:3.12-slim bash -c \
  "pip install --no-cache-dir -q -r src/requirements.txt -r tests/requirements-dev.txt && cd tests && python -m pytest -q"
```

## Typography

Base article text size is overridden in `src/static/stylesheets/extra.css`
(`.md-typeset`, `0.9rem` vs. Material's own default `0.8rem`). Change that one rule to
adjust site-wide reading size further.

## Admonition types (`!!!`/`???`)

The `!!!`/`???` blocks used throughout the posts (see the live
**[LaTeX Guide](https://math.example.com/latex-guide/)**'s "The word-problem
layout" section for the syntax itself) come from the `admonition` and `pymdownx.details`
Markdown extensions -- the word right after `!!!`/`???` is the **type**, and it maps to a
CSS class (`.md-typeset .admonition.<type>`) that controls its color and icon.

Every type used on this site today is one of Material's **built-in** types -- nothing
custom has been added yet, and none of them live in `extra.css`:

| Type | Used for | Color |
|---|---|---|
| `question` | Stating a problem | Blue |
| `info` | A neutral reference (e.g. a "Formulas" block) | Light blue |
| `success` | A worked solution/answer | Green |

Material ships a fixed set of other built-in types too (`note`, `abstract`, `tip`,
`warning`, `failure`, `danger`, `bug`, `example`, `quote`), all usable the same way with
no extra CSS.

**To add a genuinely custom type** (your own icon/color, not just reusing a built-in
one), add two rules to `src/static/stylesheets/extra.css` -- no change to the Markdown
extension config needed, since `admonition`/`pymdownx.details` already accept any type
name, they just fall back to a generic look for one they don't recognize:

```css
.md-typeset .admonition.mytype,
.md-typeset details.mytype {
  border-color: #your-color;
}

.md-typeset .mytype > .admonition-title,
.md-typeset .mytype > summary {
  background-color: #your-color-transparent;
}

.md-typeset .mytype > .admonition-title::before,
.md-typeset .mytype > summary::before {
  background-color: #your-color;
  -webkit-mask-image: var(--md-admonition-icon--note); /* or your own icon */
  mask-image: var(--md-admonition-icon--note);
}
```

Then use it exactly like a built-in type: `!!! mytype "Title"` or `??? mytype "Title"`.

## Custom CSS classes

Everything below lives in `src/static/stylesheets/extra.css`; none of it is part of
Material's own vendored theme.

| Component | Classes | Purpose |
|---|---|---|
| Categories sidebar | `.categories-panel`, `.categories-panel__toggle`, `.categories-panel__body`, `.categories-panel__title`, `.categories-panel__list` | The collapsed-by-default right-edge panel listing every category (see above). Rendered by `templates/base.html`, populated from `db.list_categories()`, toggled by `static/javascripts/categories-panel.js`. |
| Graph popup | `.plot-widget`, `.plot-widget__toggle`, `.plot-widget__modal`, `.plot-widget__backdrop`, `.plot-widget__box`, `.plot-widget__close` | The "Show graph" button and its popup (see above). Rendered by `render_plots.py`, toggled by `static/javascripts/plot-modal.js`. `.plot-widget__toggle` also uses Material's own built-in `.md-button` class for its base look, rather than reinventing button styling. |
