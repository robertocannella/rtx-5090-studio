// Add/move/delete controls for the per-block post editor (admin_form.html). Plain event
// delegation on `document`, attached once -- this is a normal full page load (not part of
// Material's instant-navigation content swapping the rest of the site uses), so the usual
// duplicate-listener hazard that pattern exists to avoid doesn't apply here either way;
// it's just the simplest way to handle a dynamically growing/reordering list of blocks
// without re-binding listeners on every add/move.
//
// This only rearranges/duplicates <div class="admin-block"> elements in the DOM -- the
// actual reassembly into one body_markdown happens server-side (render.join_segments)
// from however many name="segments" textareas exist, in whatever order they're in, when
// the form is submitted.
document.addEventListener("click", (event) => {
  if (event.target.closest("#admin-add-block")) {
    const template = document.getElementById("admin-block-template");
    document.getElementById("admin-blocks").appendChild(template.content.cloneNode(true));
    return;
  }

  const upButton = event.target.closest(".admin-block__move-up");
  if (upButton) {
    const block = upButton.closest(".admin-block");
    const previous = block.previousElementSibling;
    if (previous) block.parentNode.insertBefore(block, previous);
    return;
  }

  const downButton = event.target.closest(".admin-block__move-down");
  if (downButton) {
    const block = downButton.closest(".admin-block");
    const next = block.nextElementSibling;
    if (next) block.parentNode.insertBefore(next, block);
    return;
  }

  const deleteButton = event.target.closest(".admin-block__delete");
  if (deleteButton) {
    const block = deleteButton.closest(".admin-block");
    const container = block.parentNode;
    if (container.children.length > 1) {
      block.remove();
    } else {
      // Always leave at least one block behind -- clear it instead of removing the last one.
      block.querySelector("textarea").value = "";
    }
  }
});
