// Wires the Print / Save as PDF button on a post page (post.html), plus the optional
// "Hide answers" checkbox next to it. There's no server-side PDF generation here at all
// -- no new dependency, no headless browser -- the browser's own native print dialog
// already offers "Save as PDF" as a printer target, so this just needs a good @media
// print stylesheet (see extra.css) and a button that calls window.print() at the right
// moment.
//
// Plain event delegation on `document`, attached once at script-load time -- the button
// lives inside the post's own content, which Material's instant navigation replaces on
// every page-to-page nav, so a listener bound directly to the button itself would need
// re-binding on every navigation (see categories-panel.js's own comment for the full
// story on why that's a real, previously-hit bug here, not just theoretical).
document.addEventListener("click", (event) => {
  if (!event.target.closest("#post-print-button")) return;
  const hideAnswers = document.getElementById("post-hide-answers");
  document.body.classList.toggle("mn-print-hide-answers", Boolean(hideAnswers && hideAnswers.checked));
  window.print();
});
