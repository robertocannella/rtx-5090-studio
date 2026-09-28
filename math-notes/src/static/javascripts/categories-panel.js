// Wires the collapsed-by-default side panel's tabs (Browse, and -- admin editor only --
// Matplotlib; see base.html for the markup, stylesheets/extra.css for the styling). One
// shared body, several tabs, each showing/hiding its own .categories-panel__pane inside
// that body -- not an independent popout per tab (an earlier version gave each tab its
// own toggle+body stacked one below the other, which pushed a later tab's body down by
// however tall the earlier tabs' own toggles -- and, if open, their own bodies -- happened
// to be, reported live as the popup opening too low and unreachable below the bottom of
// the viewport).
//
// Clicking a tab: if the body is closed, or a *different* tab is currently active, open
// the body (if needed) and switch to this tab's pane. If this tab is already the open,
// active one, close the body instead -- so a second click on the same tab collapses it,
// matching how a single on/off toggle used to behave.
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
  const tab = event.target.closest("[data-panel-tab]");
  if (!tab) return;
  const panel = tab.closest(".categories-panel");
  const body = panel.querySelector(".categories-panel__body");
  if (!body) return;

  const alreadyActiveAndOpen = !body.hasAttribute("hidden") && tab.getAttribute("aria-expanded") === "true";
  if (alreadyActiveAndOpen) {
    body.setAttribute("hidden", "");
    tab.setAttribute("aria-expanded", "false");
    return;
  }

  body.removeAttribute("hidden");
  panel.querySelectorAll("[data-panel-tab]").forEach((t) => {
    t.setAttribute("aria-expanded", String(t === tab));
  });
  panel.querySelectorAll("[data-panel-pane]").forEach((pane) => {
    pane.toggleAttribute("hidden", pane.dataset.panelPane !== tab.dataset.panelTab);
  });
});
