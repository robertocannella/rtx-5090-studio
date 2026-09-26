// Renders math on the page. This is a plain multi-page site now (no more Material
// instant-navigation SPA-style swaps), and this script tag is loaded with `defer` after
// the KaTeX/auto-render CDN scripts (also `defer`, so all three run in document order,
// after the page is fully parsed) -- so a plain top-level call is all that's needed, no
// DOMContentLoaded listener or document$.subscribe re-wiring required.
renderMathInElement(document.body, {
  delimiters: [
    { left: "$$", right: "$$", display: true },
    { left: "$", right: "$", display: false },
    { left: "\\(", right: "\\)", display: false },
    { left: "\\[", right: "\\]", display: true },
  ],
});
