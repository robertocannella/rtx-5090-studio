// #post-expand-graphs-button (post.html, only rendered when the post has at least one
// graph/diagram) toggles every non-inline graph's hidden modal to show directly on the
// page -- reuses the exact same "unwrap the modal, hide the button/backdrop/close
// controls" technique the print stylesheet already applies unconditionally when printing
// (see extra.css's @media print block), just gated on a body class instead of print
// media so the same effect works on screen too, reversibly.
(function () {
  if (window.__expandGraphsLoaded) return;
  window.__expandGraphsLoaded = true;

  const button = document.getElementById("post-expand-graphs-button");
  if (!button) return;

  const label = button.querySelector(".md-ellipsis");

  button.addEventListener("click", () => {
    const expanded = document.body.classList.toggle("mn-expand-graphs");
    if (label) label.textContent = expanded ? "Collapse all graphs" : "Expand all graphs";
    button.setAttribute("aria-pressed", expanded ? "true" : "false");
  });
})();
