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

pymdownx.highlight gives ```python (etc.) fenced blocks real Pygments syntax-coloring
instead of plain unstyled text -- it has to be registered for pymdownx.superfences to
tokenize code into <span class="k">/<span class="nf">/... instead of just wrapping it in
a bare <code> tag. No CSS of our own is needed for this: static/vendor/stylesheets/
main.*.css (Material for MkDocs' own bundled theme) already ships full `.highlight .xx`
token-color rules for both the light and dark (slate) palettes, inherited from the site's
original MkDocs build -- this was previously inert because nothing actually emitted those
classes.

A single shared `markdown.Markdown` instance (not the one-shot `markdown.markdown()`
convenience function) is reused across calls so `.toc_tokens` -- the heading list the
Material-style secondary sidebar needs -- is available after each `.convert()` call.
"""

import re

import markdown

EXTENSIONS = [
    "admonition",
    "pymdownx.details",
    "pymdownx.highlight",
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

# Matches the marker with its `!` optional -- a one-key typo that's easy to make on a
# touchscreen keyboard's cramped symbol layout (confirmed live: a real post's `<-- more
# -->`, missing just the `!`, wasn't recognized at all, leaving it to show up as a stray
# literal `<-- more -->` on the live page instead of silently splitting the excerpt).
# Used everywhere EXCERPT_MARKER itself used to be compared/searched for exactly, so a
# mistyped marker is treated identically to a correct one throughout -- both in the
# actual render (split_excerpt) and in the admin block editor's segment classification
# (split_into_segments/classify_segment), not just one or the other.
EXCERPT_MARKER_RE = re.compile(r"<!?--\s*more\s*-->")

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
    match = EXCERPT_MARKER_RE.search(raw_markdown)
    if match:
        excerpt = raw_markdown[:match.start()]
        full = EXCERPT_MARKER_RE.sub("", raw_markdown)
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


_FENCE_PREFIX = "```"
_MATH_OPENERS = {"\\[": "\\]", "$$": "$$"}


def _is_indented(line):
    return line.startswith("    ") or line.startswith("\t")


def split_into_segments(text):
    """Splits a post's raw Markdown into an ordered list of top-level block strings --
    a paragraph, a heading, a whole `!!!`/`???` admonition (including everything nested
    under it), a whole fenced code block, a whole `$$`/`\\[` math block, or the
    `<!-- more -->` marker -- so the admin editor can show one smaller textarea per block
    instead of one giant one. `join_segments` is the inverse: reassembling the list this
    returns always reproduces markdown that renders identically to the original (verified
    against every real post in the live database, not just synthetic examples).

    This never looks inside a block to sub-divide it further -- an admonition's internal
    math/paragraphs stay part of that one block, matching the editor's actual goal (edit
    *a* problem/solution/graph at a time, not fight the granularity of Markdown's own
    grammar).
    """
    lines = text.split("\n")
    n = len(lines)
    segments = []
    i = 0

    while i < n:
        while i < n and lines[i].strip() == "":
            i += 1
        if i >= n:
            break

        stripped = lines[i].strip()

        if stripped.startswith(_FENCE_PREFIX):
            start = i
            i += 1
            while i < n and not lines[i].strip().startswith(_FENCE_PREFIX):
                i += 1
            if i < n:
                i += 1  # include the closing fence
            segments.append("\n".join(lines[start:i]))
            continue

        if stripped in _MATH_OPENERS:
            closer = _MATH_OPENERS[stripped]
            start = i
            i += 1
            while i < n and lines[i].strip() != closer:
                i += 1
            if i < n:
                i += 1  # include the closing marker
            segments.append("\n".join(lines[start:i]))
            continue

        if EXCERPT_MARKER_RE.fullmatch(stripped):
            segments.append(lines[i])
            i += 1
            continue

        if stripped.startswith("!!!") or stripped.startswith("???"):
            start = i
            end = i + 1
            i += 1
            while i < n:
                if lines[i].strip() == "":
                    j = i
                    while j < n and lines[j].strip() == "":
                        j += 1
                    if j < n and _is_indented(lines[j]):
                        i = j  # blank line(s) followed by more indented content -- internal
                        continue
                    break  # blank line(s) followed by a new block, or end of text -- stop
                if _is_indented(lines[i]):
                    i += 1
                    end = i
                else:
                    break
            segments.append("\n".join(lines[start:end]))
            i = end
            continue

        # A plain paragraph or heading -- runs until a blank line or the start of one of
        # the block types above, however many lines that is (a soft-wrapped paragraph
        # stays one segment, matching how Markdown itself treats it as one block).
        start = i
        i += 1
        while i < n:
            s = lines[i].strip()
            if s == "" or s.startswith(_FENCE_PREFIX) or s in _MATH_OPENERS or EXCERPT_MARKER_RE.fullmatch(s) \
                    or s.startswith("!!!") or s.startswith("???"):
                break
            i += 1
        segments.append("\n".join(lines[start:i]))

    return segments


def join_segments(segments):
    """Inverse of split_into_segments -- blank-line-separated, matching the convention
    every other block-level construct on this site already assumes (split_excerpt,
    normalize_display_math_spacing).
    """
    return "\n\n".join(s.strip() for s in segments if s.strip())


def classify_segment(segment):
    """A short label for the admin editor to show above a segment's textarea -- purely
    cosmetic, recomputed fresh from content every time, never stored."""
    stripped = segment.strip()
    first_line = stripped.split("\n", 1)[0].strip()
    if EXCERPT_MARKER_RE.fullmatch(first_line):
        return "Excerpt break"
    if first_line.startswith("```matplotlib"):
        return "Matplotlib graph"
    if first_line.startswith(_FENCE_PREFIX):
        return "Code block"
    if first_line in _MATH_OPENERS:
        return "Math block"
    if first_line.startswith("!!!") or first_line.startswith("???"):
        m = re.match(r'^(?:!!!|\?\?\?)\s*(\S+)', first_line)
        kind = m.group(1) if m else ""
        prefix = "Admonition" if first_line.startswith("!!!") else "Collapsible"
        return f"{prefix} ({kind})" if kind else prefix
    if first_line.startswith("#"):
        return "Heading"
    return "Paragraph"


_DETAILS_TAG_RE = re.compile(r"<details\b")


def expand_details_blocks(html):
    """Forces every `??? type "Title"` collapsible block (rendered as <details> by
    pymdownx.details) open -- used only for the admin editor's per-block view-mode
    preview (app.py's _render_segment_preview), never for the public site, where staying
    collapsed by default is the whole point (so a reader can attempt a problem before
    revealing the solution).

    The editor's view mode is meant to show a block fully expanded, both so nothing needs
    manually expanding to review it and because clicking a native <summary> toggle (which
    lives inside the view pane) bubbles up like any other click there -- without this, the
    very click meant to reveal a collapsed block's content was instead read as "click the
    view pane -> enter edit mode" (admin-blocks.js's view-click handler also explicitly
    excludes summary/button/link clicks from that, as defense in depth against the same
    bubbling for whatever's still natively clickable after this).
    """
    return _DETAILS_TAG_RE.sub("<details open", html)


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


def needs_solving(body_html):
    """True for a post with no `??? success`/`!!! success` Solution block yet -- this
    site's own established convention for a word problem's worked answer (see the print
    stylesheet's "Hide answers" feature, which targets the exact same two class forms).
    Deliberately derived from the rendered HTML rather than a separate stored flag on the
    post itself: a flag can go stale the moment a Solution block is actually added (an
    easy thing to forget to also un-flag by hand); checking the real content directly
    means a "Needs solving" badge disappears automatically, for every post site-wide, the
    instant a real solution exists -- nothing to remember to update in two places.

    Two substring checks, not one, for the same reason `extra.css`'s print "Hide
    answers" rule needs two selectors: python-markdown's two admonition extensions
    render their class attribute differently for the exact same "success" type -- a
    non-collapsible `!!! success` block gets `class="admonition success"`, but a
    collapsible `??? success` block (what every actual Solution on this site uses) gets
    `class="success"` alone, with no "admonition" class at all.
    """
    return 'class="admonition success"' not in body_html and 'class="success"' not in body_html
