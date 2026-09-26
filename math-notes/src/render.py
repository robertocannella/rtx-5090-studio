"""Markdown -> HTML rendering for math-notes posts, done once at save time (db.py calls
this from create_post()/update_post()), not per page view.

Uses the same Python-Markdown extensions the site's earlier MkDocs-based build used --
admonition (!!! blocks), pymdownx.details (??? collapsible blocks), pymdownx.superfences,
attr_list, md_in_html (lets render_plots.py's raw HTML <div> output pass through
untouched), and pymdownx.arithmatex in "generic" mode. arithmatex just wraps $...$/$$...$$
math in <span>/<div class="arithmatex"> markers -- it does not render the math itself;
that still happens client-side, in the reader's browser, via KaTeX
(static/javascripts/katex.js) exactly as it did on the static MkDocs site. None of this
needed to change when the site moved from a build-time static generator to a per-request
dynamic app -- it's the same library either way, just invoked directly here instead of
through MkDocs' own build pipeline.
"""

import markdown

EXTENSIONS = [
    "admonition",
    "pymdownx.details",
    "pymdownx.superfences",
    "attr_list",
    "md_in_html",
    "pymdownx.arithmatex",
    "tables",
    "toc",
]

EXTENSION_CONFIGS = {
    "pymdownx.arithmatex": {"generic": True},
    "toc": {"permalink": True},
}

EXCERPT_MARKER = "<!-- more -->"


def render_markdown(text):
    return markdown.markdown(text, extensions=EXTENSIONS, extension_configs=EXTENSION_CONFIGS)


def split_excerpt(raw_markdown):
    """(excerpt_markdown, full_markdown) -- excerpt is everything before the first
    <!-- more --> marker (or the whole post, if there's no marker); full is the whole
    post with the marker itself stripped out. Mirrors the MkDocs blog plugin's own
    excerpt-splitting convention exactly, so existing posts need no rewriting.
    """
    if EXCERPT_MARKER in raw_markdown:
        excerpt, _, _ = raw_markdown.partition(EXCERPT_MARKER)
        full = raw_markdown.replace(EXCERPT_MARKER, "")
        return excerpt.strip(), full.strip()
    return raw_markdown.strip(), raw_markdown.strip()
