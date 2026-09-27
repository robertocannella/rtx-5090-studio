// Add/move/delete/edit-toggle controls for the per-block post editor (admin_form.html).
//
// Only one block is ever in edit mode at a time: switching a different block into edit
// mode first finalizes whichever block was being edited, fetching a live render of
// exactly what's currently typed in it (POST /admin/preview-segment -- stateless, saves
// nothing to the database) so its view mode reflects in-progress edits, not just the
// last save.
//
// Plain event delegation on `document`, attached once -- this is a normal full page load
// (not part of Material's instant-navigation content swapping the rest of the site uses),
// so the usual duplicate-listener hazard that pattern exists to avoid doesn't apply here
// either way; it's just the simplest way to handle a dynamically growing/reordering list
// of blocks without re-binding listeners on every add/move.

const ADMIN_BLOCKS_KATEX_DELIMITERS = [
  { left: "$$", right: "$$", display: true },
  { left: "$", right: "$", display: false },
  { left: "\\(", right: "\\)", display: false },
  { left: "\\[", right: "\\]", display: true },
];

function adminBlocksRenderMath(el) {
  if (window.renderMathInElement) {
    renderMathInElement(el, { delimiters: ADMIN_BLOCKS_KATEX_DELIMITERS });
  }
}

async function adminBlockSwitchToView(block) {
  const textarea = block.querySelector("textarea");
  const view = block.querySelector(".admin-block__view");
  const text = textarea.value;
  if (!text.trim()) {
    view.innerHTML = "";
  } else {
    try {
      const resp = await fetch("/admin/preview-segment", {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: "text=" + encodeURIComponent(text),
      });
      view.innerHTML = await resp.text();
      adminBlocksRenderMath(view);
    } catch (err) {
      // A transient network error here shouldn't block anything -- Save (a real form
      // submit) is what actually matters, and it doesn't depend on this preview at all.
    }
  }
  block.dataset.mode = "view";
  block.querySelector(".admin-block__toggle").textContent = "Edit";
}

function adminBlockSwitchToEdit(block) {
  block.dataset.mode = "edit";
  block.querySelector(".admin-block__toggle").textContent = "Done";
  block.querySelector("textarea").focus();
}

function adminBlockEnterEditMode(block) {
  const currentlyEditing = document.querySelector('.admin-block[data-mode="edit"]');
  if (currentlyEditing && currentlyEditing !== block) {
    adminBlockSwitchToView(currentlyEditing).then(() => adminBlockSwitchToEdit(block));
  } else {
    adminBlockSwitchToEdit(block);
  }
}

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
      adminBlockSwitchToEdit(block);
    }
    return;
  }

  const toggleButton = event.target.closest(".admin-block__toggle");
  if (toggleButton) {
    const block = toggleButton.closest(".admin-block");
    if (block.dataset.mode === "edit") {
      adminBlockSwitchToView(block);
    } else {
      adminBlockEnterEditMode(block);
    }
    return;
  }

  // Clicking directly on a block's rendered view (not one of its buttons) also opens it
  // for editing -- the Edit button is there for discoverability, but most block editors
  // let you just click into the content itself.
  const view = event.target.closest(".admin-block__view");
  if (view) {
    const block = view.closest(".admin-block");
    if (block.dataset.mode === "view") {
      adminBlockEnterEditMode(block);
    }
  }
});
