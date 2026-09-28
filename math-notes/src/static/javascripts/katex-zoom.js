// A-/A+ buttons -- in the site header, and in every admin block's own header (see
// admin_form.html) -- let a viewer zoom KaTeX-rendered math up or down, independently of
// the rest of the page's text size. Any element anywhere with a data-katex-zoom-in/-out
// attribute works via this same delegated listener, so the per-block buttons needed no
// JS changes of their own to wire up. On public pages, tapping a formula directly does
// the same thing -- right half zooms in, left half zooms out -- so zooming in to read
// one equation doesn't require a trip back up to the header. All paths set exactly one
// CSS custom property (--katex-zoom, see extra.css) that every .katex element on the
// page already multiplies its own font-size by -- a public post, the LaTeX guide, and
// the admin editor's view-mode preview panes all pick this up automatically, with
// nothing here needing to know which kind of page it's on.
//
// Formula-tap-to-zoom is deliberately skipped inside .admin-block__view (the admin
// block editor's own view panes): clicking a block there is how you switch it into edit
// mode (see admin-blocks.js), and formulas are common enough in this site's content that
// tap-to-zoom taking priority over that meant clicking a formula to start editing it
// silently zoomed instead -- reported live as "I miss having the block turn editable
// when clicking on it." Per-block header buttons are the replacement, not a removal --
// zooming math while editing a post is still one click away, just not a tap on the
// formula itself anymore.
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

  function stepZoom(delta) {
    currentZoom = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, currentZoom + delta));
    // Round to avoid accumulating floating-point noise (0.1 + 0.2 !== 0.3, etc.) across
    // repeated clicks.
    currentZoom = Math.round(currentZoom * 10) / 10;
    applyZoom(currentZoom);
    saveZoom(currentZoom);
  }

  function isRightHalf(formula, clientX) {
    const rect = formula.getBoundingClientRect();
    return clientX - rect.left > rect.width / 2;
  }

  document.addEventListener("click", (event) => {
    const zoomInButton = event.target.closest("[data-katex-zoom-in]");
    const zoomOutButton = event.target.closest("[data-katex-zoom-out]");
    if (zoomInButton || zoomOutButton) {
      stepZoom(zoomInButton ? STEP : -STEP);
      return;
    }

    // A tap directly on a rendered formula zooms it too -- right half in, left half out --
    // without needing the header buttons at all. Excludes the copy-LaTeX button (a
    // .katex-display's own child, not .katex's) so copying a formula's source never also
    // zooms it, and excludes the admin block editor's own view panes (see the comment
    // above) so a click there always means "edit this block," formula or not.
    if (event.target.closest(".katex-copy")) return;
    if (event.target.closest(".admin-block__view")) return;
    const formula = event.target.closest(".katex");
    if (!formula) return;
    stepZoom(isRightHalf(formula, event.clientX) ? STEP : -STEP);
  });

  // A faint -/+ near the formula's own left/right edge previews which half you're over,
  // before you click -- otherwise "tap a formula to zoom it" has no visible affordance at
  // all. Pure CSS (extra.css's .katex-zoom-hover--left/--right rules, gated to
  // hover-capable pointers) driven by these two classes; this only ever toggles them, it
  // never touches opacity/positioning directly. mouseout's relatedTarget check is the
  // standard way to get mouseleave-like behavior (fires once when the pointer truly
  // leaves .katex, not on every move between its inner glyph spans) out of a single
  // delegated listener, rather than binding enter/leave per formula.
  document.addEventListener("mousemove", (event) => {
    if (event.target.closest(".admin-block__view")) return;
    const formula = event.target.closest(".katex");
    if (!formula) return;
    const rightHalf = isRightHalf(formula, event.clientX);
    formula.classList.toggle("katex-zoom-hover--left", !rightHalf);
    formula.classList.toggle("katex-zoom-hover--right", rightHalf);
  });

  document.addEventListener("mouseout", (event) => {
    const formula = event.target.closest(".katex");
    if (!formula || formula.contains(event.relatedTarget)) return;
    formula.classList.remove("katex-zoom-hover--left", "katex-zoom-hover--right");
  });
})();
