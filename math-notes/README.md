# Math Notes

A public math/physics blog at **https://math.example.com** built with
[MkDocs](https://www.mkdocs.org/) + [Material for MkDocs](https://squidfunk.github.io/mkdocs-material/),
with LaTeX rendered by [KaTeX](https://katex.org/). See
`/srv/apps/docs/MATH-NOTES.md` (on `docs.example.com`) for the full
architecture writeup -- this file is the short, practical "how do I add a
post" reference.

## This is a static site -- every change needs a rebuild

There's no database and no live editor. Adding or editing a Markdown file
does nothing to the live site by itself -- it has to be rebuilt into HTML
and redeployed:

```bash
cd /srv/apps/math-notes
docker compose up -d --build
```

`mkdocs build --strict` runs as part of that build and **fails the build**
on a broken internal link or a bad markdown-extension reference, rather
than silently shipping a broken page.

## Adding a new post

Create a file under `docs/blog/posts/`, named `YYYY-MM-DD-a-short-slug.md`:

```markdown
---
date: 2026-09-24
categories:
  - Algebra
---

# Post title

The opening paragraph -- this is what shows up as the excerpt on the blog
index page.

<!-- more -->

The rest of the post goes here, only shown on the post's own page.
```

- `date` drives sort order, the RSS feed, and the "September 24, 2026" line
  shown on the post.
- `categories` can list more than one; each one gets its own
  auto-generated archive page at `/blog/category/<name>/`, and shows as a
  small tag on the post's card on the blog index.
- The `<!-- more -->` marker is what splits "excerpt shown on the index"
  from "rest of the post" -- put it right after the intro paragraph.
- Nothing else needs updating -- the blog plugin auto-discovers every file
  under `blog/posts/` and rebuilds the index, categories, and RSS feed from
  scratch on every build.

## Writing math and word problems

See the live **[LaTeX Guide](https://math.example.com/latex-guide/)**
page (`docs/latex-guide.md`) -- it covers inline vs. display math, a
cheat-sheet of common LaTeX syntax, and the `!!! question` / `??? success`
problem/solution pattern used throughout the posts here.

## Adding a non-blog page

Pages outside the blog (like this guide, or the homepage) are plain
Markdown files under `docs/`, listed explicitly in `mkdocs.yml`'s `nav:`
section -- add the file, then add a line to `nav:` so it shows up as a top
nav tab (`navigation.tabs` is enabled, so every top-level `nav:` entry
renders as a tab across the top of every page).

## Local preview before deploying

To check a change renders correctly without touching the live container:

```bash
cd /srv/apps/math-notes
docker build -t math-notes:local .
docker run --rm -p 8080:80 math-notes:local
# open http://localhost:8080
```

`docker build` alone (without `docker run`) is also enough to catch a
`--strict`-mode build failure (a typo'd link, a malformed admonition, etc.)
without needing to actually view the page.
