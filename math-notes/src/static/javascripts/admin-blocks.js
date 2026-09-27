// Add/move/delete/edit-toggle controls for the per-block post editor (admin_form.html).
//
// Only one block is ever in edit mode at a time: switching a different block into edit
// mode first finalizes whichever block was being edited, fetching a live render of
// exactly what's currently typed in it (POST /admin/preview-segment -- stateless, saves
// nothing to the database) so its view mode reflects in-progress edits, not just the
// last save. A matplotlib block's own Generate graph button is the one case that
// genuinely executes its code on purpose (POST /admin/generate-graph, into a scratch
// directory the real save path never reads from) -- everything else here only ever
// renders, never runs, whatever is currently typed.
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
  if (window.mnInjectKatexCopyButtons) {
    // Same copy-the-LaTeX-source button every display math block gets on public pages
    // (see katex.js) -- this is the other place math actually gets rendered (a block's
    // view-mode preview), so it needs its own call to pick up freshly-rendered math here.
    window.mnInjectKatexCopyButtons(el);
  }
}

const ADMIN_BLOCKS_INDENT = "    "; // 4 spaces, matching every admonition/details block's
                                     // continuation indent throughout this site's actual
                                     // post content -- not a literal tab character, so a
                                     // Tab keystroke here stays consistent with everything
                                     // already written (and with what render.py's
                                     // split_into_segments/normalize_display_math_spacing
                                     // already treat as "indented").

// A plain <textarea> only ever emits Tab as a focus-navigation key, moving focus to
// whatever's next in tab order (here, the Save button) instead of typing anything -- for
// a Markdown editor, where indentation is meaningful (admonition/details bodies), that is
// almost never what's wanted. This intercepts Tab/Shift+Tab in any block's textarea and
// turns it into indent/outdent instead, the same convention essentially every code editor
// uses. A single-line, no-selection Tab just inserts the indent at the cursor; a
// multi-line selection indents/outdents every line it touches, so nesting an existing
// paragraph under an admonition (select it, press Tab) doesn't mean re-typing it by hand.
function adminBlockHandleTab(textarea, shiftKey) {
  const value = textarea.value;
  const selectionStart = textarea.selectionStart;
  const selectionEnd = textarea.selectionEnd;
  const lineStart = value.lastIndexOf("\n", selectionStart - 1) + 1;
  const spansMultipleLines = value.slice(selectionStart, selectionEnd).includes("\n");

  if (!shiftKey && !spansMultipleLines) {
    textarea.value = value.slice(0, selectionStart) + ADMIN_BLOCKS_INDENT + value.slice(selectionEnd);
    const cursor = selectionStart + ADMIN_BLOCKS_INDENT.length;
    textarea.selectionStart = textarea.selectionEnd = cursor;
    return;
  }

  let lineEnd = value.indexOf("\n", selectionEnd);
  lineEnd = lineEnd === -1 ? value.length : lineEnd;
  const before = value.slice(0, lineStart);
  const after = value.slice(lineEnd);
  const lines = value.slice(lineStart, lineEnd).split("\n");

  let firstLineDelta = 0;
  const newLines = lines.map((line, i) => {
    if (shiftKey) {
      let cut = 0;
      if (line.startsWith(ADMIN_BLOCKS_INDENT)) cut = ADMIN_BLOCKS_INDENT.length;
      else if (line.startsWith("\t")) cut = 1;
      else {
        const leading = line.match(/^ +/);
        if (leading) cut = Math.min(leading[0].length, ADMIN_BLOCKS_INDENT.length);
      }
      if (i === 0) firstLineDelta = -cut;
      return line.slice(cut);
    }
    if (i === 0) firstLineDelta = ADMIN_BLOCKS_INDENT.length;
    return ADMIN_BLOCKS_INDENT + line;
  });

  const newBlock = newLines.join("\n");
  textarea.value = before + newBlock + after;
  textarea.selectionStart = Math.max(lineStart, selectionStart + firstLineDelta);
  textarea.selectionEnd = lineStart + newBlock.length;
}

document.addEventListener("keydown", (event) => {
  if (event.key !== "Tab") return;
  const textarea = event.target;
  if (textarea.tagName !== "TEXTAREA" || !textarea.closest(".admin-block")) return;
  event.preventDefault();
  adminBlockHandleTab(textarea, event.shiftKey);
});

async function adminBlockRenderInto(view, text, url, extraParams = {}) {
  if (!text.trim()) {
    view.innerHTML = "";
    return;
  }
  try {
    const params = new URLSearchParams({ text, ...extraParams });
    const resp = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: params.toString(),
    });
    view.innerHTML = await resp.text();
    adminBlocksRenderMath(view);
  } catch (err) {
    // A transient network error here shouldn't block anything -- Save (a real form
    // submit) is what actually matters, and it doesn't depend on this preview at all.
  }
}

async function adminBlockSwitchToView(block) {
  const textarea = block.querySelector("textarea");
  const view = block.querySelector(".admin-block__view");
  // The post's own slug (blank for a brand new, not-yet-saved post) -- needed so an
  // already-saved matplotlib block's preview looks in the right directory for its PNG
  // (see app.py's _render_segment_preview for why).
  const slug = document.getElementById("admin-blocks").dataset.postSlug || "";
  await adminBlockRenderInto(view, textarea.value, "/admin/preview-segment", { slug });
  block.dataset.mode = "view";
  block.querySelector(".admin-block__toggle").textContent = "Edit";
}

// A ```matplotlib block's code is never executed just by looking at it (see
// adminBlockRenderInto/preview-segment) -- the Generate graph button is the one
// explicit, author-initiated exception, so it's only shown for a block that currently
// looks like a matplotlib block, checked live as the author types (a brand new "+ Add
// block" starts out as a plain paragraph until it actually contains one).
const ADMIN_BLOCKS_MATPLOTLIB_FENCE_RE = /```matplotlib\s+name="/;

function adminBlockUpdateGenerateGraphVisibility(block) {
  const textarea = block.querySelector("textarea");
  const button = block.querySelector(".admin-block__generate-graph");
  button.hidden = !ADMIN_BLOCKS_MATPLOTLIB_FENCE_RE.test(textarea.value);
}

document.addEventListener("input", (event) => {
  const block = event.target.closest(".admin-block");
  if (block && event.target.tagName === "TEXTAREA") {
    adminBlockUpdateGenerateGraphVisibility(block);
  }
});

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
    // A block being actively edited may hold unsaved changes (or just be easy to delete
    // by reflex while mid-edit) -- a settled, view-mode block is already reflected in the
    // last render either way, so only the edit-mode case is worth interrupting for.
    if (block.dataset.mode === "edit" && !confirm("Discard this block and its unsaved changes?")) {
      return;
    }
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

  const generateButton = event.target.closest(".admin-block__generate-graph");
  if (generateButton) {
    const block = generateButton.closest(".admin-block");
    const textarea = block.querySelector("textarea");
    const view = block.querySelector(".admin-block__view");
    adminBlockRenderInto(view, textarea.value, "/admin/generate-graph").then(() => {
      block.dataset.mode = "view";
      block.querySelector(".admin-block__toggle").textContent = "Edit";
    });
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
  // let you just click into the content itself. This must NOT fire for a click on
  // something natively interactive inside the rendered content itself (a <summary>
  // toggling a details block open/closed again, a link, an image, a rendered formula
  // tapped to zoom it -- see katex-zoom.js) -- those clicks bubble up here the same as
  // any other click in the view pane, and should do their own native thing rather than
  // being read as "enter edit mode" (render.expand_details_blocks starts every details
  // block open specifically to avoid needing this click in the first place, but the
  // native toggle remains clickable regardless of its initial state).
  const view = event.target.closest(".admin-block__view");
  if (view && !event.target.closest("summary, a, button, img, .katex")) {
    const block = view.closest(".admin-block");
    if (block.dataset.mode === "view") {
      adminBlockEnterEditMode(block);
    }
  }
});
