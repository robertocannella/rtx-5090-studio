// A-/A+ buttons in the header let a viewer zoom KaTeX-rendered math up or down,
// independently of the rest of the page's text size. Sets exactly one CSS custom
// property (--katex-zoom, see extra.css) that every .katex element on the page already
// multiplies its own font-size by -- a public post, the LaTeX guide, and the admin
// editor's view-mode preview panes all pick this up automatically, with nothing here
// needing to know which kind of page it's on.
//
// Persisted in localStorage per browser (not per site-wide setting -- this is a reading
// preference, not content), wrapped in try/catch since a private window or blocked site
// data can make it throw; the zoom level just falls back to the default (1) rather than
// breaking the page.
(function () {
  const STORAGE_KEY = "mn_katex_zoom";
  const MIN_ZOOM = 0.7;
  const MAX_ZOOM = 2.2;
  const STEP = 0.1;
  const DEFAULT_ZOOM = 1;

  function loadZoom() {
    try {
      const stored = parseFloat(localStorage.getItem(STORAGE_KEY));
      return Number.isFinite(stored) ? stored : DEFAULT_ZOOM;
    } catch (err) {
      return DEFAULT_ZOOM;
    }
  }

  function saveZoom(zoom) {
    try {
      localStorage.setItem(STORAGE_KEY, String(zoom));
    } catch (err) {
      // Falls back to defaulting again next load -- not worth surfacing to the viewer.
    }
  }

  function applyZoom(zoom) {
    document.documentElement.style.setProperty("--katex-zoom", zoom);
  }

  let currentZoom = loadZoom();
  applyZoom(currentZoom);

  document.addEventListener("click", (event) => {
    const zoomInButton = event.target.closest("[data-katex-zoom-in]");
    const zoomOutButton = event.target.closest("[data-katex-zoom-out]");
    if (!zoomInButton && !zoomOutButton) return;

    const delta = zoomInButton ? STEP : -STEP;
    currentZoom = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, currentZoom + delta));
    // Round to avoid accumulating floating-point noise (0.1 + 0.2 !== 0.3, etc.) across
    // repeated clicks.
    currentZoom = Math.round(currentZoom * 10) / 10;
    applyZoom(currentZoom);
    saveZoom(currentZoom);
  });
})();
