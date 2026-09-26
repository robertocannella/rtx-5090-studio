"""Builds the search index JSON that Material's real search worker (vendored verbatim
under static/vendor/javascripts/workers/) expects at /search/search_index.json --
the exact same {config, docs} shape mkdocs-material's own search plugin used to write to
disk at build time, just assembled from the database on request instead.

One entry per page (not per heading, unlike the original build-time plugin) -- coarser
granularity, but the whole index is rebuilt from scratch on every request from whatever
posts exist right now, so there's no staleness to worry about, and this site is small
enough that per-page results are still quite usable.
"""

import re

_TAG_RE = re.compile(r"<[^>]+>")

# Matches the config the real search worker was built against (captured from an actual
# mkdocs-material build's search/search_index.json) -- not something to invent by hand.
CONFIG = {
    "lang": ["en"],
    "separator": "[\\s\\-]+",
    "pipeline": ["stopWordFilter"],
    "fields": {
        "title": {"boost": 1000.0},
        "text": {"boost": 1.0},
        "tags": {"boost": 1000000.0},
    },
}


def _plain_text(html):
    return " ".join(_TAG_RE.sub(" ", html).split())


def build_index(home_html, latex_guide_html, posts):
    docs = [
        {"location": "", "title": "Math Notes", "text": _plain_text(home_html)},
        {"location": "latex-guide/", "title": "LaTeX Guide", "text": _plain_text(latex_guide_html)},
    ]
    for post in posts:
        docs.append({
            "location": f"blog/{post['slug']}/",
            "title": post["title"],
            "text": _plain_text(post["body_html"]),
        })
    return {"config": CONFIG, "docs": docs}
