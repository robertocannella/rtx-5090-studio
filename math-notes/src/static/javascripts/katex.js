// Renders math after every page load, including Material's instant-navigation page
// swaps (document$ is Material's own navigation observable, not a typo of `document`) --
// without subscribing to that instead of a plain DOMContentLoaded listener, math on any
// page reached via instant navigation (the default, see mkdocs.yml's navigation.instant)
// would never get rendered after the first page load.
document$.subscribe(({ body }) => {
  renderMathInElement(body, {
    delimiters: [
      { left: "$$", right: "$$", display: true },
      { left: "$", right: "$", display: false },
      { left: "\\(", right: "\\)", display: false },
      { left: "\\[", right: "\\]", display: true },
    ],
  });
  mnInjectKatexCopyButtons(body);
});

// A small copy-the-source button on every *display* math block (not inline $...$ -- one
// on every small inline symbol would clutter far more than it'd help). KaTeX already
// embeds the exact LaTeX it was given as a MathML <annotation> alongside its visual
// rendering (that's a KaTeX/MathML accessibility feature, not something added here) --
// this only ever reads that back out, never a second copy of the source stored anywhere.
// Exposed on window rather than only running from this file's own document$.subscribe
// above, so admin-blocks.js's own (non-Material, fetch-driven) re-renders of a single
// block's view pane can call it too after their own renderMathInElement pass.
function mnInjectKatexCopyButtons(root) {
  root.querySelectorAll(".katex-display").forEach((el) => {
    if (el.querySelector(".katex-copy")) return;
    const annotation = el.querySelector('annotation[encoding="application/x-tex"]');
    if (!annotation) return;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "katex-copy";
    button.title = "Copy LaTeX";
    button.setAttribute("data-latex", annotation.textContent);
    el.style.position = "relative";
    el.appendChild(button);
  });
}
window.mnInjectKatexCopyButtons = mnInjectKatexCopyButtons;

document.addEventListener("click", (event) => {
  const button = event.target.closest(".katex-copy");
  if (!button) return;
  const latex = button.getAttribute("data-latex") || "";
  navigator.clipboard.writeText(latex).then(
    () => {
      button.classList.add("katex-copy--copied");
      button.title = "Copied!";
      setTimeout(() => {
        button.classList.remove("katex-copy--copied");
        button.title = "Copy LaTeX";
      }, 1200);
    },
    () => {
      // Clipboard API blocked (permissions, non-secure context) -- nothing sensible to
      // fall back to silently; leaving the button's title unchanged is honest about it
      // not having worked, rather than claiming success it didn't have.
    },
  );
});
