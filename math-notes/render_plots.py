"""Pre-build step (run from the Dockerfile *before* `mkdocs build`): scans every blog
post for fenced ```matplotlib code blocks, executes each one's plotting code, saves the
resulting figure as a PNG under docs/assets/plots/<name>.png, and rewrites the post in
place so the code block becomes a "Show graph" button that opens the image in a modal --
see docs/latex-guide.md's "Adding a graph" section for the author-facing syntax, and
docs/javascripts/plot-modal.js / docs/stylesheets/extra.css for the button/modal markup
and behavior this generates.

This runs as a plain script, not an MkDocs hook, because it has to run *before*
`on_files` decides which files exist to copy into the built site. An MkDocs hook that
runs during page processing (on_page_markdown) fires after that decision has already
been made -- an image saved that late would never make it into the output. Running this
first, so every generated PNG already exists on disk before `mkdocs build` even starts,
sidesteps that ordering problem entirely.
"""

import re
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless -- there's no display server in the build container
import matplotlib.pyplot as plt  # noqa: E402 - must follow matplotlib.use()

DOCS_DIR = Path(__file__).parent / "docs"
POSTS_DIR = DOCS_DIR / "blog" / "posts"
PLOTS_DIR = DOCS_DIR / "assets" / "plots"

# ```matplotlib name="..." title="..."   (title optional)
# <python code>
# ```
FENCE_RE = re.compile(
    r'```matplotlib\s+name="(?P<name>[^"]+)"(?:\s+title="(?P<title>[^"]+)")?[ \t]*\n'
    r"(?P<code>.*?)\n```",
    re.DOTALL,
)


def render_one(name: str, code: str) -> Path:
    """Executes `code` (expected to build a plot via matplotlib -- e.g. plt.plot(...),
    ax.plot(...)) and saves whatever figure it produced. The author's code should not
    call plt.savefig() itself -- this always saves the current figure to the path this
    function controls, so the image location stays deterministic (docs/assets/plots/
    named after the block's own `name`) regardless of what the author's code does.
    """
    plt.close("all")
    namespace = {"plt": plt}
    exec(compile(code, f"<matplotlib block: {name}>", "exec"), namespace)  # noqa: S102 - trusted, self-authored post content, not user input
    fig = plt.gcf()
    if not fig.get_axes():
        raise RuntimeError(
            f"matplotlib block {name!r} produced no figure/axes -- did the code actually plot anything?"
        )
    PLOTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = PLOTS_DIR / f"{name}.png"
    fig.savefig(out_path, bbox_inches="tight", dpi=150)
    plt.close(fig)
    return out_path


def widget_html(name: str, title: str | None, image_rel_path: Path) -> str:
    label = title or "Show graph"
    src = "/" + image_rel_path.as_posix()
    return (
        f'<div class="plot-widget">\n'
        f'<button type="button" class="md-button plot-widget__toggle" data-plot="{name}">{label}</button>\n'
        f'<div class="plot-widget__modal" id="plot-modal-{name}" hidden>\n'
        f'<div class="plot-widget__backdrop" data-plot-close="{name}"></div>\n'
        f'<div class="plot-widget__box">\n'
        f'<button type="button" class="plot-widget__close" data-plot-close="{name}" aria-label="Close">&times;</button>\n'
        f'<img src="{src}" alt="{label}">\n'
        f"</div>\n"
        f"</div>\n"
        f"</div>\n"
    )


def process_post(path: Path) -> None:
    text = path.read_text(encoding="utf-8")

    def replace(match: re.Match) -> str:
        name = match.group("name")
        title = match.group("title")
        code = match.group("code")
        out_path = render_one(name, code)
        rel = out_path.relative_to(DOCS_DIR)
        print(f"  {path.name}: rendered {name!r} -> {rel}")
        return widget_html(name, title, rel)

    new_text, count = FENCE_RE.subn(replace, text)
    if count:
        path.write_text(new_text, encoding="utf-8")


def main() -> None:
    if not POSTS_DIR.exists():
        return
    for path in sorted(POSTS_DIR.glob("*.md")):
        process_post(path)


if __name__ == "__main__":
    sys.exit(main())
