"""Executes ```matplotlib fenced code blocks in a post's raw markdown, once, at save
time (create/update, not per page view) -- see the LaTeX Guide's "Adding a graph"
section for the author-facing syntax.
"""

import contextlib
import io
import re
from html import escape as _escape
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless -- no display server in the container
import matplotlib.pyplot as plt  # noqa: E402 - must follow matplotlib.use()

# ```matplotlib name="..." title="..." inline="true"   (title, inline both optional --
# and in that order: inline is only recognized after title, or right after name if
# title is omitted entirely, same as title itself is already order-locked after name)
# <python code>
# ```
FENCE_RE = re.compile(
    r'```matplotlib\s+name="(?P<name>[^"]+)"(?:\s+title="(?P<title>[^"]+)")?'
    r'(?:\s+inline="(?P<inline>[^"]+)")?[ \t]*\n'
    r"(?P<code>.*?)\n```",
    re.DOTALL,
)


def _is_true(value):
    return (value or "").strip().lower() == "true"


class PlotError(Exception):
    pass


def _render_one(name, code, plots_dir):
    """Executes `code` (expected to build a plot -- e.g. ax.plot(...)) and saves
    whatever figure it produced. The author's code should not call plt.savefig() itself
    -- this always saves the current figure to a path this function controls, keyed only
    on the block's own `name`, so the image location stays deterministic regardless of
    what the author's code does.

    Returns (out_path, output) -- output is whatever the code printed (e.g. a computed
    acceleration or a checked value), captured rather than left to go to the container's
    own stdout/logs where a reader would never see it. Persisted alongside the PNG as
    `{name}.txt` so process_preview (which never re-executes code) can show the same
    printed output a previous real save produced, not just the image -- and removed if a
    block that used to print something no longer does, so a stale value never lingers
    after the code that produced it is gone.
    """
    plt.close("all")
    namespace = {"plt": plt}
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
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

    output = buf.getvalue()
    output_path = plots_dir / f"{name}.txt"
    if output.strip():
        output_path.write_text(output)
    elif output_path.exists():
        output_path.unlink()
    return out_path, output


def _output_html(output):
    return f'<pre class="plot-widget__output">{_escape(output.rstrip())}</pre>' if output.strip() else ""


def _versioned_src(png_path, assets_url_prefix, name):
    """A `?v=<mtime>` query string on every graph image's URL -- the filename itself
    never changes across regenerations (same `name` every time, by design), so without
    this a browser can keep showing bytes from before the latest edit: reported live as
    "sometimes it's cached and doesn't update," most noticeably right after clicking
    Generate graph and expecting the preview to reflect a just-made code change. Tied to
    the PNG's own mtime (not a fresh timestamp computed here) so process_preview -- which
    never re-executes code, only ever points at whatever a real save already produced --
    still busts the cache correctly after a save changed the file out from under it.
    """
    return f"{assets_url_prefix}/{name}.png?v={int(png_path.stat().st_mtime_ns)}"


def _modal_html(name, label, src, output=""):
    return (
        f'<div class="plot-widget__modal" id="plot-modal-{name}" hidden>\n'
        f'<div class="plot-widget__backdrop" data-plot-close="{name}"></div>\n'
        f'<div class="plot-widget__box">\n'
        f'<button type="button" class="plot-widget__close" data-plot-close="{name}" aria-label="Close">&times;</button>\n'
        f'<img src="{src}" alt="{label}">\n'
        f"{_output_html(output)}"
        f"</div>\n</div>\n"
    )


def _widget_html(name, title, src, output="", inline=False):
    """Two very different DOMs depending on `inline` -- both open the exact same modal
    (see plot-modal.js, which opens whatever `#plot-modal-{name}` belongs to any clicked
    element carrying a `data-plot` attribute, button or image alike):

    - Default (inline=False): a "Show graph" button; the image itself only exists inside
      the modal, invisible until clicked.
    - inline=True: the image is visible directly in the post's normal reading flow --
      no click needed to see it at all -- but is itself the click target for the same
      enlarge-in-a-modal behavior the button gives, via the same data-plot attribute.
      Whatever the code printed sits right next to the always-visible image, not
      duplicated again inside the modal (the modal's only job here is a bigger look at
      the same image, not a second copy of everything).
    """
    label = title or "Show graph"
    if inline:
        return (
            f'<div class="plot-widget plot-widget--inline">\n'
            f'<img class="plot-widget__inline-img" src="{src}" alt="{label}" '
            f'data-plot="{name}" title="Click to enlarge">\n'
            f"{_output_html(output)}"
            f"{_modal_html(name, label, src)}"
            f"</div>\n"
        )
    return (
        f'<div class="plot-widget">\n'
        f'<button type="button" class="md-button plot-widget__toggle" data-plot="{name}">{label}</button>\n'
        f"{_modal_html(name, label, src, output)}"
        f"</div>\n"
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
        inline = _is_true(match.group("inline"))
        out_path, output = _render_one(name, code, plots_dir)
        src = _versioned_src(out_path, assets_url_prefix, name)
        return _widget_html(name, title, src, output, inline=inline)

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
        out_path, output = _render_one(name, code, plots_dir)
        src = _versioned_src(out_path, assets_url_prefix, name)
        return f'<div class="plot-widget__preview"><img src="{src}" alt="{title}">{_output_html(output)}</div>'

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
        png_path = plots_dir / f"{name}.png"
        if png_path.exists():
            src = _versioned_src(png_path, assets_url_prefix, name)
            output_path = plots_dir / f"{name}.txt"
            output = output_path.read_text() if output_path.exists() else ""
            return (
                f'<div class="plot-widget__preview"><img src="{src}" alt="{title}">'
                f"{_output_html(output)}</div>"
            )
        return (
            '<p class="plot-widget__pending"><em>'
            f"Graph {name!r} will render here after you save."
            "</em></p>"
        )

    return FENCE_RE.sub(replace, markdown_text)
