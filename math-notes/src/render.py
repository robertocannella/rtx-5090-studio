"""Markdown -> HTML rendering for math-notes content (blog posts, the home page, the
LaTeX guide), done once at save time for posts (db.py calls this from
create_post()/update_post()) and once per request for the two static pages, which are
short enough that re-parsing them each time is not worth caching.

Uses the same Python-Markdown extensions the site's original MkDocs-based build used --
admonition (!!! blocks), pymdownx.details (??? collapsible blocks), pymdownx.superfences,
attr_list, md_in_html (lets render_plots.py's raw HTML <div> output pass through
untouched), tables, and pymdownx.arithmatex in "generic" mode. arithmatex just wraps
$...$/$$...$$ math in <span>/<div class="arithmatex"> markers -- it does not render the
math itself; that still happens client-side, via KaTeX (static/javascripts/katex.js).

A single shared `markdown.Markdown` instance (not the one-shot `markdown.markdown()`
convenience function) is reused across calls so `.toc_tokens` -- the heading list the
Material-style secondary sidebar needs -- is available after each `.convert()` call.
"""

import re

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

WORDS_PER_MINUTE = 220


def _new_md():
    return markdown.Markdown(extensions=EXTENSIONS, extension_configs=EXTENSION_CONFIGS)


def render_markdown(text):
    """(html, toc_tokens) -- toc_tokens is python-markdown's own list of
    {"level", "id", "name", "children"} dicts, one per heading, matching what the `toc`
    extension builds for its own (unused here) rendered ToC.
    """
    md = _new_md()
    html = md.convert(text)
    return html, md.toc_tokens


def split_excerpt(raw_markdown):
    """(excerpt_markdown, full_markdown) -- excerpt is everything before the first
    <!-- more --> marker (or the whole post, if there's no marker); full is the whole
    post with the marker itself stripped out. Mirrors the MkDocs blog plugin's own
    excerpt-splitting convention, so existing posts need no rewriting.
    """
    if EXCERPT_MARKER in raw_markdown:
        excerpt, _, _ = raw_markdown.partition(EXCERPT_MARKER)
        full = raw_markdown.replace(EXCERPT_MARKER, "")
        return excerpt.strip(), full.strip()
    return raw_markdown.strip(), raw_markdown.strip()


def normalize_display_math_spacing(text):
    """Both `$$...$$` and `\\[...\\]` display-math blocks (pymdownx.arithmatex's "dollar"
    and "square" block_syntax) only get recognized when the *pair* of markers is isolated
    from surrounding text by a blank line, exactly like any other block-level Markdown
    construct (a fenced code block, a blockquote) -- a blank line before the opening
    marker and after the closing one, but never between a marker and the content next to
    it inside the pair. Content pasted from ChatGPT (which writes \\[ ... \\] immediately
    butted up against the surrounding prose, no blank line at all) fails that requirement
    silently: arithmatex's block processor just doesn't match, core Markdown's ordinary
    backslash-escape handling strips the backslash instead, and `\\[x\\]` renders as the
    literal text `[x]`.

    This inserts the missing blank line on the *outside* of each pair, so the author
    never has to remember to add it by hand -- purely whitespace normalization, no change
    to any actual math content. `\\[`/`\\]` are unambiguous; `$$` uses the same string for
    both ends of a pair, so occurrences are tracked in order (1st = open, 2nd = close, ...).
    """
    lines = text.split("\n")
    out = []
    in_dollar_block = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        nxt = lines[i + 1] if i + 1 < len(lines) else None

        if stripped == "\\[" or (stripped == "$$" and not in_dollar_block):
            if out and out[-1].strip() != "":
                out.append("")
            out.append(line)
            if stripped == "$$":
                in_dollar_block = True
        elif stripped == "\\]" or (stripped == "$$" and in_dollar_block):
            out.append(line)
            if stripped == "$$":
                in_dollar_block = False
            if nxt is not None and nxt.strip() != "":
                out.append("")
        else:
            out.append(line)
    return "\n".join(out)


def secondary_toc(toc_tokens):
    """Material's secondary sidebar never lists the page's own top-level heading (its
    title is already shown as the page heading itself) -- only what's nested under it.
    python-markdown's toc extension nests everything under a single root entry whenever
    a page has exactly one top-level heading (true for every page/post on this site), so
    this unwraps that one level. Falls back to the raw list for the (currently unused)
    case of a page with no heading, or more than one top-level heading.
    """
    if len(toc_tokens) == 1:
        return toc_tokens[0].get("children", [])
    return toc_tokens


_TAG_RE = re.compile(r"<[^>]+>")


def reading_time_minutes(html):
    """Matches Material's own blog plugin display ("N min read"): plain word count over
    the rendered HTML with tags stripped, divided by a fixed reading speed, rounded up,
    minimum of 1.
    """
    text = _TAG_RE.sub(" ", html)
    words = len(text.split())
    return max(1, round(words / WORDS_PER_MINUTE) or 1)
