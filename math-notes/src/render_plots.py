"""Executes ```matplotlib fenced code blocks in a post's raw markdown, once, at save
time (create/update, not per page view) -- see the LaTeX Guide's "Adding a graph"
section for the author-facing syntax.
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
        f'<button type="button" class="md-button plot-widget__toggle" data-plot="{name}">{label}</button>\n'
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


def process_live(markdown_text, plots_dir, assets_url_prefix="/assets/plots"):
    """Like process() -- actually executes each block's code -- but for the admin
    editor's explicit "Generate graph" action, not a save: renders the result as a plain
    visible <img>, matching the editor's "show it expanded" convention
    (expand_details_blocks/process_preview), rather than the public site's click-to-reveal
    button+modal.

    Unlike process_preview, this genuinely runs the block's code and can raise
    PlotError -- that is the point of a button the author clicks on purpose to see
    whether their in-progress code actually works. The caller must always pass a scratch
    `plots_dir` distinct from the real one create_post()/update_post() write to: an
    abandoned edit (Generate graph clicked, then navigated away without saving the post)
    must never change what a live, already-published post's graph looks like.
    """
    plots_dir = Path(plots_dir)

    def replace(match):
        name = match.group("name")
        title = match.group("title") or "Graph"
        code = match.group("code")
        _render_one(name, code, plots_dir)
        return f'<p class="plot-widget__preview"><img src="{assets_url_prefix}/{name}.png" alt="{title}"></p>'

    return FENCE_RE.sub(replace, markdown_text)


def process_preview(markdown_text, plots_dir, assets_url_prefix="/assets/plots"):
    """Renders a ```matplotlib block for the admin editor's per-block view-mode preview
    (app.py's _render_segment_preview) -- but never executes the block's code, only ever
    points at whatever PNG a real save has already produced for that `name`. Previewing
    an edit is not saving it, and a block's code can be mid-edit/syntactically broken at
    any moment while its view is being rendered, so this must never have the side effects
    (or failure modes) that actually running arbitrary matplotlib code has. If a block's
    name has never been saved yet, shows a placeholder instead of a broken <img>.

    Unlike process() (the public site's click-to-reveal button+modal), this renders the
    image directly and visibly -- the editor's view mode is meant to show a block fully
    expanded by default, not require a click to reveal it while reviewing/editing.
    """
    plots_dir = Path(plots_dir)

    def replace(match):
        name = match.group("name")
        title = match.group("title") or "Graph"
        if (plots_dir / f"{name}.png").exists():
            src = f"{assets_url_prefix}/{name}.png"
            return f'<p class="plot-widget__preview"><img src="{src}" alt="{title}"></p>'
        return (
            '<p class="plot-widget__pending"><em>'
            f"Graph {name!r} will render here after you save."
            "</em></p>"
        )

    return FENCE_RE.sub(replace, markdown_text)
