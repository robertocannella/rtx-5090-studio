# Math Notes

A public math blog at **`math.example.com`** -- personal notes, derivations, and
worked word problems, written in Markdown with real LaTeX math. Unlike everything else in
this doc set, this one is meant to be read by other people, not just as an operator
reference.

## Why MkDocs, not WordPress

The alternative on the table was WordPress plus a LaTeX plugin. MkDocs (specifically
[Material for MkDocs](https://squidfunk.github.io/mkdocs-material/)) was chosen instead
because:

- **No database, no PHP** -- content is Markdown files in `/srv/apps/math-notes/docs/`,
  built once into static HTML/CSS/JS. Nothing to patch, nothing that can get SQL-injected,
  nothing with its own login/admin surface to secure.
- **Real LaTeX, not a plugin's approximation** -- math is rendered client-side by
  [KaTeX](https://katex.org/), the same library used by many serious math sites, rather
  than a WordPress plugin that often renders formulas to small server-side images.
- **Fits the existing stack exactly** -- git-tracked content, a Dockerfile, a `compose.yaml`
  joining `edge`, and a Caddy route, the same pattern as every other app under `/srv/apps`.

## Architecture

```text
Browser (math.example.com)
  |
Caddy (no basic_auth -- this one's meant to be public)
  |
edge
  |
math-notes (nginx serving a pre-built static site)
```

`math-notes` is a **two-stage Docker build** (`Dockerfile`): stage one is a throwaway
`python:3.12-slim` image with `mkdocs-material` and `mkdocs-rss-plugin` installed, which
runs `mkdocs build --strict` (fails the build on any broken link/reference, not just
warns) to produce static output in `site/`; stage two is a bare `nginx:alpine` that only
ever contains that generated `site/` directory. The running container has no Python, no
pip, and no source Markdown in it at all -- only genuinely static files.

## Writing a post

Add a Markdown file under `docs/blog/posts/`, named `YYYY-MM-DD-slug.md`, with YAML
frontmatter:

```markdown
---
date: 2026-09-24
categories:
  - Algebra
---

# Post title

Intro paragraph (shown as the excerpt on the blog index).

<!-- more -->

The rest of the post, only shown on the post's own page.
```

The `blog` plugin (built into `mkdocs-material`, not a separate package) auto-discovers
everything under `blog/posts/` and builds the index, category pages, and pagination --
there's no separate "publish" step or manifest to update beyond adding the file itself.
`mkdocs-rss-plugin` generates an RSS feed (`feed_rss_created.xml`) from the same frontmatter
dates, with `use_git: false` set in `mkdocs.yml` since the Docker build context here is
just this app's own files, not a git checkout the plugin's git-history fallback could read.

**LaTeX**: inline math is `$...$`, display math is a `$$ ... $$` block on its own lines,
exactly like writing real LaTeX. This is `pymdownx.arithmatex` (`generic: true`) wrapping
the math in spans that `docs/javascripts/katex.js` finds and renders via KaTeX after each
page load -- including Material's instant-navigation page swaps (`document$.subscribe`,
not a plain `DOMContentLoaded` listener, is what makes math still render on a page reached
without a full reload).

**Word problems**: state the problem in a `!!! question "Problem"` admonition, then the
answer in a `??? success "Solution"` block -- the `???` (vs `!!!`) makes it collapsed by
default, so a reader can attempt the problem before revealing the answer. See
`docs/blog/posts/2026-09-24-welcome.md` for a worked example of both LaTeX and this pattern
together.

**Two other references live alongside this one, closer to the code**: `math-notes/README.md`
is the short, practical "how do I add a post" reference (a repo-root README, not part of
the built site itself); `docs/latex-guide.md` is a live page on the site itself
(`math.example.com/latex-guide/`) walking through inline vs. display math,
superscript/subscript/fractions/roots with worked examples, and a symbol cheat-sheet --
useful both for a reader and for future-you writing the next post.

## Navigation

`navigation.tabs` (a `theme.features` entry) turns every top-level `nav:` entry in
`mkdocs.yml` into a persistent tab across the top of every page -- currently Home, Blog,
and LaTeX Guide. Adding a new non-blog page means adding both the `.md` file under `docs/`
and a line to `nav:`; blog posts need neither, since the `blog` plugin auto-discovers them.

Material's breadcrumb feature (`navigation.path`) was tried and dropped -- it's an
Insiders-only feature and silently renders nothing in the open-source `mkdocs-material`
package this app actually uses (confirmed by inspecting the built HTML, not just the
changelog). The blog plugin's `categories_toc`/`archive_toc` options were tried for the
same "more navigation" goal and also dropped after confirming, the same way, that they
don't add anything visible to this site's pages either.

### Categories sidebar

A small, custom, collapsed-by-default panel pinned to the right edge of every page,
listing every category that exists across all posts, each linking to its
`/blog/category/<name>/` archive page. Since Material has no built-in widget for this
(see above), it's three custom pieces:

- **`hooks.py`** (wired via `mkdocs.yml`'s `hooks:`) -- a build-time hook that scans every
  file under `blog/posts/` for its YAML frontmatter `categories` list and stores the sorted,
  de-duplicated result in `config.extra.all_categories`. Reads raw frontmatter straight off
  disk in `on_files` rather than relying on `Page.meta`, since that isn't guaranteed
  populated for every page yet at that point in MkDocs' own build sequence. Add a new
  category to a post's frontmatter and it just shows up in the sidebar on the next build --
  nothing else to update.
- **`overrides/main.html`** (wired via `theme.custom_dir: overrides`) -- a Jinja template
  override rendering the panel's HTML from `config.extra.all_categories`. It's a sibling
  directory to `docs/`, not inside it -- `custom_dir` templates are Jinja sources MkDocs
  renders with, not static content to publish, so putting them under `docs/` would make
  MkDocs try to build `overrides/main.html` itself as a page.
- **`docs/stylesheets/extra.css`** / **`docs/javascripts/categories-panel.js`** -- the fixed-position
  styling and the click-to-toggle behavior (`document$.subscribe`, the same
  Material-instant-navigation-aware pattern as `katex.js`, since the panel's DOM is part of
  what gets replaced on every page swap).

**Why `overrides/main.html` overrides the `scripts` block, not `content`**: the first
version of this override placed the panel's markup in `{% block content %}`, which worked
on plain pages (Home, LaTeX Guide) but the panel was silently missing on every blog
page -- the index, individual posts, and category archives. Reading the actual templates
shipped inside the installed `mkdocs-material` package (not just guessing from the docs)
showed why: `blog.html` and `blog-post.html` both `{% extends "main.html" %}`, but both
override the `container` block wholesale, without calling `{{ super() }}` -- which
discards the nested `content` block substitution entirely for any page rendered through
either of them. `scripts` is a block neither of those templates touches at all, so
overriding it instead is what actually makes the panel appear on every page type
consistently, confirmed the same way (built the site, `curl`'d each of the four page
types -- home, blog index, an individual post, a category archive -- and grepped for the
panel's markup in each).

## Deploying a change

```bash
cd /srv/apps/math-notes
docker compose up -d --build
```

`mkdocs build --strict` runs as part of that build -- a typo'd internal link or a
markdown-extension config mistake fails the build loudly instead of silently shipping a
broken page.

## DNS and TLS

`math.example.com` needs an A/CNAME record added in Cloudflare pointing at the
same target as this server's other subdomains -- this isn't something that can be done
from the server itself. Until that record exists, Caddy's automatic HTTPS certificate
request for it will keep failing (`no valid A records found`) and retrying on its own
schedule (`docker logs gateway`); once the record is added, the next retry succeeds
without needing to touch the gateway again.

## Not mirrored to the public showcase repo

`scripts/export-showcase.sh` copies every git-tracked file under `/srv/apps` into the
separate `rtx-5090-studio` showcase repo (redacting the real domain/credentials) -- but
`math-notes/docs/` is excluded from that copy. The showcase repo is about
demonstrating this server's *infrastructure*; a personal math blog's actual writing isn't
infrastructure, and it's already public in its own right at `math.example.com`, so
mirroring its content into a second, differently-purposed public repo would just be
clutter. The app's `Dockerfile`/`compose.yaml`/`mkdocs.yml` (the infrastructure part) are
still exported normally.
