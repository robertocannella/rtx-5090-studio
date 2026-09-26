"""Executes ```matplotlib fenced code blocks in a post's raw markdown, once, at save
time (create/update, not per page view) -- see the live LaTeX Guide's "Adding a graph"
section for the author-facing syntax.

This is the dynamic-app version of the original MkDocs-build-time render_plots.py: that
one scanned .md files on disk as a Docker build step; this one processes a single
markdown string, called directly from db.py whenever a post is created or updated.
"""

import re
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless -- no display server in the container
import matplotlib.pyplot as plt  # noqa: E402 - must follow matplotlib.use()

# ```matplotlib name="..." title="..."   (title optional)
# <python code>
# ```
FENCE_RE = re.compile(
    r'```matplotlib\s+name="(?P<name>[^"]+)"(?:\s+title="(?P<title>[^"]+)")?[ \t]*\n'
    r"(?P<code>.*?)\n```",
    re.DOTALL,
)


class PlotError(Exception):
    pass


def _render_one(name, code, plots_dir):
    """Executes `code` (expected to build a plot -- e.g. ax.plot(...)) and saves
    whatever figure it produced. The author's code should not call plt.savefig() itself
    -- this always saves the current figure to a path this function controls, keyed only
    on the block's own `name`, so the image location stays deterministic regardless of
    what the author's code does.
    """
    plt.close("all")
    namespace = {"plt": plt}
    try:
        exec(compile(code, f"<matplotlib block: {name}>", "exec"), namespace)  # noqa: S102 - trusted, self-authored post content, not arbitrary user input
    except Exception as e:  # noqa: BLE001 - want to report exactly which block failed
        raise PlotError(f"matplotlib block {name!r} failed: {e}") from e
    fig = plt.gcf()
    if not fig.get_axes():
        raise PlotError(f"matplotlib block {name!r} produced no figure/axes -- did the code actually plot anything?")
    plots_dir.mkdir(parents=True, exist_ok=True)
    out_path = plots_dir / f"{name}.png"
    fig.savefig(out_path, bbox_inches="tight", dpi=150)
    plt.close(fig)
    return out_path


def _widget_html(name, title, src):
    label = title or "Show graph"
    return (
        f'<div class="plot-widget">\n'
        f'<button type="button" class="btn plot-widget__toggle" data-plot="{name}">{label}</button>\n'
        f'<div class="plot-widget__modal" id="plot-modal-{name}" hidden>\n'
        f'<div class="plot-widget__backdrop" data-plot-close="{name}"></div>\n'
        f'<div class="plot-widget__box">\n'
        f'<button type="button" class="plot-widget__close" data-plot-close="{name}" aria-label="Close">&times;</button>\n'
        f'<img src="{src}" alt="{label}">\n'
        f"</div>\n</div>\n</div>\n"
    )


def process(markdown_text, plots_dir, assets_url_prefix="/assets/plots"):
    """Replaces every ```matplotlib block in markdown_text with a button+modal HTML
    snippet, rendering each one's image as a side effect. Safe to call on text with no
    such blocks at all (returns it unchanged).
    """
    plots_dir = Path(plots_dir)

    def replace(match):
        name = match.group("name")
        title = match.group("title")
        code = match.group("code")
        _render_one(name, code, plots_dir)
        return _widget_html(name, title, f"{assets_url_prefix}/{name}.png")

    return FENCE_RE.sub(replace, markdown_text)
