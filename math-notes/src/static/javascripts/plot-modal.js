// Opens/closes the "Show graph" popup(s) rendered by render_plots.py. Unlike
// categories-panel.js (which re-wires its listener inside document$.subscribe on every
// Material instant-navigation page swap, since its own toggle button gets replaced by
// each swap), this attaches its listeners once, directly on `document` -- delegated
// listeners survive every page swap automatically, since `document` itself is never
// replaced, only its descendant content is. No per-page rewiring needed either way.
document.addEventListener("click", (event) => {
  const opener = event.target.closest(".plot-widget__toggle");
  if (opener) {
    const modal = document.getElementById(`plot-modal-${opener.dataset.plot}`);
    if (modal) modal.hidden = false;
    return;
  }
  const closer = event.target.closest("[data-plot-close]");
  if (closer) {
    const modal = document.getElementById(`plot-modal-${closer.dataset.plotClose}`);
    if (modal) modal.hidden = true;
  }
});

document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;
  document.querySelectorAll(".plot-widget__modal:not([hidden])").forEach((modal) => {
    modal.hidden = true;
  });
});
