// Wires the collapsed-by-default categories panel's toggle button (see
// overrides/main.html for the markup, stylesheets/extra.css for the styling).
//
// This used to re-wire itself inside document$.subscribe, on the assumption that
// Material's instant navigation replaces the panel's DOM on every page swap the same way
// it replaces the main content area. It doesn't: the panel is rendered from the `scripts`
// block (see overrides/main.html's comment on why), which sits outside the content area
// instant navigation actually swaps, so the button's DOM node persists unchanged across
// every page-to-page navigation. document$.subscribe still fired on every navigation
// though, and each firing created a brand new closure and attached it as an *additional*
// listener on that same persistent button (a fresh arrow function is never == the
// previous one, so the browser doesn't deduplicate it) -- so after visiting even one
// other page, a single click fired two listeners back to back, which toggled the panel
// open then immediately closed again: clicking the button appeared to do nothing at all
// once you'd navigated anywhere.
//
// Plain event delegation on `document`, attached exactly once here at script-load time,
// fixes this categorically: `document` itself is never replaced by instant navigation
// (only descendant content is), so this listener is never re-attached, no matter how
// many pages get visited or whether the button's own node persists or gets recreated.
document.addEventListener("click", (event) => {
  const toggle = event.target.closest(".categories-panel__toggle");
  if (!toggle) return;
  const body = document.querySelector(".categories-panel__body");
  if (!body) return;
  const collapsed = body.hasAttribute("hidden");
  if (collapsed) {
    body.removeAttribute("hidden");
  } else {
    body.setAttribute("hidden", "");
  }
  toggle.setAttribute("aria-expanded", String(collapsed));
});
