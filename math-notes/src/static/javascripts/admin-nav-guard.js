// Material's instant-loading (bundle.js, driven by the "navigation.instant" feature flag
// in base.html's __config block) treats every same-origin link click as an AJAX-fetched
// content swap instead of a real page load -- including into, out of, or between admin
// pages, which were never designed to survive that. admin-blocks.js (loaded only on
// admin_form.html) declares top-level `const`s; a second execution in the same
// never-reloaded JS global scope -- exactly what an instant-nav swap does NOT reset --
// throws a fatal "already been declared" SyntaxError (confirmed live, in a real browser
// console, via a user-provided screenshot). Because that's a *parse*-time error, nothing
// else in the file runs either, so whatever admin-blocks.js was supposed to (re)wire up
// for that freshly swapped-in page's specific elements silently never happens.
//
// Fix: force every navigation into, out of, or between admin pages to be a real browser
// navigation, so admin-blocks.js always gets a clean, single, true page load, the same
// assumption its own top-of-file comment already (incorrectly, until now) relied on.
//
// A capture-phase listener on `document` is used specifically because capture-phase
// listeners are *guaranteed* to run before any bubble-phase listener on the same target --
// including bundle.js's own click handler -- regardless of which `<script>` tag happened
// to load first; a bubble-phase listener here could not reliably win that race.
document.addEventListener(
  "click",
  (event) => {
    if (event.defaultPrevented || event.button !== 0) return;
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return; // open-in-new-tab etc. -- leave alone
    const link = event.target.closest("a[href]");
    if (!link) return;

    let url;
    try {
      url = new URL(link.href, location.href);
    } catch {
      return;
    }
    if (url.origin !== location.origin) return;

    // A same-page fragment link -- the Matplotlib reference panel's own "Jump to" list
    // (added after this file), or any heading's own ¶ permalink -- never triggers
    // Material's instant-loading page-swap machinery in the first place; only an actual
    // navigation to a *different* path does. Forcing one through window.location.href
    // here anyway, instead of leaving it to the browser's own native, lightweight
    // same-page scroll-to-anchor handling, risked more than it protected against:
    // reported live as losing an in-progress block's unsaved text just from clicking a
    // Jump to link while mid-edit.
    if (url.pathname === location.pathname && url.search === location.search) return;

    const isAdminPath = (pathname) => pathname === "/admin" || pathname.startsWith("/admin/");
    if (!isAdminPath(location.pathname) && !isAdminPath(url.pathname)) return;

    event.preventDefault();
    event.stopImmediatePropagation();
    window.location.href = link.href;
  },
  { capture: true },
);
