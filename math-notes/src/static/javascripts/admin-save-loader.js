// Shows a brief, informative overlay the moment Save is clicked, listing exactly which
// matplotlib blocks are about to be (re-)rendered server-side -- reported live: "when
// saving, sometimes the graph generation takes time ... add a loader that says what the
// backend is doing. saving graph using the name supplied". A plain, unmodified native
// form submission still does all the real work here -- this never calls
// preventDefault() or otherwise intercepts the POST, it only shows UI while the
// browser's own navigation to whatever comes next (a success redirect, or a
// validation-error re-render of this same form) is already under way, and disappears on
// its own the instant that happens either way, so there is nothing to explicitly hide
// again afterward.
(function () {
  if (window.__adminSaveLoaderLoaded) return;
  window.__adminSaveLoaderLoaded = true;

  // Mirrors render_plots.py's FENCE_RE (name required first, title/inline both
  // optional, in that fixed order) closely enough to find every block's own `name` --
  // this only has to be good enough to describe what's about to happen, not to be the
  // authoritative parser (render_plots.py itself remains that).
  const MATPLOTLIB_FENCE_RE = /```matplotlib\s+name="([^"]+)"(?:\s+title="([^"]+)")?(?:\s+inline="([^"]+)")?[ \t]*\n([\s\S]*?)\n```/g;

  function adminSaveFindGraphs(form) {
    const graphs = [];
    form.querySelectorAll('textarea[name="segments"]').forEach((textarea) => {
      MATPLOTLIB_FENCE_RE.lastIndex = 0;
      let match;
      while ((match = MATPLOTLIB_FENCE_RE.exec(textarea.value)) !== null) {
        const [, name, , , code] = match;
        // A heuristic, not a guarantee (it'd also match e.g. a plain comment mentioning
        // the word) -- but animated blocks are specifically the slow ones worth calling
        // out, and this costs nothing to get right in the common case.
        graphs.push({ name, animated: /FuncAnimation/.test(code) });
      }
    });
    return graphs;
  }

  function adminSaveShowOverlay(graphs) {
    const overlay = document.getElementById("admin-save-overlay");
    const list = document.getElementById("admin-save-overlay-graphs");
    if (!overlay) return;
    if (list) {
      list.innerHTML = "";
      list.hidden = graphs.length === 0;
      graphs.forEach(({ name, animated }) => {
        const li = document.createElement("li");
        li.textContent = animated ? `${name} (animated — may take longer)` : name;
        list.appendChild(li);
      });
    }
    overlay.hidden = false;
  }

  const form = document.querySelector("form.admin-form");
  if (form) {
    form.addEventListener("submit", () => {
      adminSaveShowOverlay(adminSaveFindGraphs(form));
    });
  }
})();
