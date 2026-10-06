// Autosaves the in-progress post -- title/category/tags and every block's raw text --
// to its own `drafts` row every couple of minutes (POST /admin/draft). Deliberately a
// separate table, keyed by "post:<id>" (an existing post) or "new:<token>" (one not
// saved yet, see admin_form.html's hidden #admin-draft-key input), never the real
// `posts` row a reader's actual page reflects -- an autosave can never collide with, let
// alone silently overwrite, a real Save (a plain, independent form submit either way).
// Recovering one is just reloading the same edit/new-post URL: app.py's GET handlers
// check for a matching draft and, if one exists, render the form from it instead of the
// last real save, with a banner offering to discard it and go back to the saved version.
(function () {
  if (window.__adminAutosaveLoaded) return;
  window.__adminAutosaveLoaded = true;

  const ADMIN_AUTOSAVE_INTERVAL_MS = 2 * 60 * 1000;

  function adminAutosaveCollect(form) {
    const title = form.querySelector('[name="title"]')?.value ?? "";
    const category = form.querySelector('[name="category"]')?.value ?? "";
    const tags = form.querySelector('[name="tags"]')?.value ?? "";
    const segments = Array.from(form.querySelectorAll('textarea[name="segments"]')).map((t) => t.value);
    return { title, category, tags, segments };
  }

  let adminAutosaveLastSnapshot = null;

  async function adminAutosaveTick() {
    const keyInput = document.getElementById("admin-draft-key");
    const form = document.querySelector("form.admin-form");
    const status = document.getElementById("admin-autosave-status");
    if (!keyInput || !keyInput.value || !form) return;

    const { title, category, tags, segments } = adminAutosaveCollect(form);
    const snapshot = JSON.stringify({ title, category, tags, segments });
    if (snapshot === adminAutosaveLastSnapshot) return; // nothing changed since the last tick -- skip the write
    if (!title.trim() && !category.trim() && segments.every((s) => !s.trim())) return; // nothing worth saving yet

    const params = new URLSearchParams({ key: keyInput.value, title, category, tags });
    segments.forEach((s) => params.append("segments", s));

    try {
      const resp = await fetch("/admin/draft", {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: params.toString(),
      });
      if (!resp.ok) return;
      adminAutosaveLastSnapshot = snapshot;
      if (status) {
        const now = new Date();
        status.textContent = `Draft autosaved at ${now.toLocaleTimeString()}`;
      }
    } catch (err) {
      // A transient network error here isn't worth surfacing -- the next tick tries
      // again, and a real Save doesn't depend on this succeeding at all.
    }
  }

  if (document.getElementById("admin-draft-key")) {
    setInterval(adminAutosaveTick, ADMIN_AUTOSAVE_INTERVAL_MS);
  }
})();
