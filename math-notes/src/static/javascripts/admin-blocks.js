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

// A block's header and footer each carry their own full copy of the controls (see
// admin_form.html/admin_block_controls) -- these two helpers keep both copies' toggle
// label / generate-graph visibility in sync, since a plain querySelector would only ever
// find (and update) the first one.
function adminBlockSetToggleLabel(block, label) {
  block.querySelectorAll(".admin-block__toggle").forEach((toggle) => {
    toggle.textContent = label;
  });
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
  adminBlockSetToggleLabel(block, "Edit");
}

// A ```matplotlib block's code is never executed just by looking at it (see
// adminBlockRenderInto/preview-segment) -- the Generate graph button is the one
// explicit, author-initiated exception, so it's only shown for a block that currently
// looks like a matplotlib block, checked live as the author types (a brand new "+ Add
// block" starts out as a plain paragraph until it actually contains one).
const ADMIN_BLOCKS_MATPLOTLIB_FENCE_RE = /```matplotlib\s+name="/;

function adminBlockUpdateGenerateGraphVisibility(block) {
  const textarea = block.querySelector("textarea");
  const isMatplotlibBlock = ADMIN_BLOCKS_MATPLOTLIB_FENCE_RE.test(textarea.value);
  block.querySelectorAll(".admin-block__generate-graph").forEach((button) => {
    button.hidden = !isMatplotlibBlock;
  });
}

// Ctrl+/ (or Cmd+/ on a Mac) toggles a Python "# " line-comment prefix on the current
// line, or every line the selection spans -- the same convention essentially every code
// editor uses. Only wired up inside a block that currently looks like a matplotlib
// block (same ADMIN_BLOCKS_MATPLOTLIB_FENCE_RE check as the Generate graph button above)
// -- the code being edited there is real Python, where "#" is one unambiguous comment
// syntax everyone already knows. Markdown/LaTeX prose has no equivalent single-character
// comment convention (an HTML comment is block-delimited, not a per-line prefix, and
// raises its own questions -- where a multi-line selection's <!-- / --> should land,
// how to detect "already commented" to toggle back off), so this deliberately does
// nothing there for now rather than guessing at a convention nobody asked for yet.
const ADMIN_BLOCKS_COMMENT_PREFIX_RE = /^(\s*)#\s?/;

function adminBlockToggleComment(textarea) {
  const value = textarea.value;
  const selectionStart = textarea.selectionStart;
  const selectionEnd = textarea.selectionEnd;
  const lineStart = value.lastIndexOf("\n", selectionStart - 1) + 1;
  let lineEnd = value.indexOf("\n", selectionEnd);
  lineEnd = lineEnd === -1 ? value.length : lineEnd;

  const before = value.slice(0, lineStart);
  const after = value.slice(lineEnd);
  const lines = value.slice(lineStart, lineEnd).split("\n");

  // Blank lines never factor into the toggle direction (nothing to comment or
  // uncomment) -- uncomment only if every *non-blank* touched line is already
  // commented; otherwise comment all of them, matching how comment-toggling works in
  // most code editors when a selection is a mix of commented and uncommented lines.
  const contentLines = lines.filter((line) => line.trim() !== "");
  const shouldUncomment = contentLines.length > 0 && contentLines.every((line) => ADMIN_BLOCKS_COMMENT_PREFIX_RE.test(line));

  let firstLineDelta = 0;
  const newLines = lines.map((line, i) => {
    if (line.trim() === "") return line;
    if (shouldUncomment) {
      const newLine = line.replace(ADMIN_BLOCKS_COMMENT_PREFIX_RE, "$1");
      if (i === 0) firstLineDelta = newLine.length - line.length;
      return newLine;
    }
    if (i === 0) firstLineDelta = 2;
    return `# ${line}`;
  });

  const newBlock = newLines.join("\n");
  textarea.value = before + newBlock + after;
  textarea.selectionStart = Math.max(lineStart, selectionStart + firstLineDelta);
  textarea.selectionEnd = lineStart + newBlock.length;
}

document.addEventListener("keydown", (event) => {
  if (event.key !== "/" || !(event.ctrlKey || event.metaKey)) return;
  const textarea = event.target;
  const block = textarea.closest(".admin-block");
  if (textarea.tagName !== "TEXTAREA" || !block) return;
  if (!ADMIN_BLOCKS_MATPLOTLIB_FENCE_RE.test(textarea.value)) return;
  event.preventDefault();
  adminBlockToggleComment(textarea);
  // Setting .value programmatically (unlike a real keystroke) never fires its own
  // "input" event, so these two don't run on their own afterward -- called by hand to
  // stay consistent with what typing the exact same change would have triggered
  // (Generate graph's visibility depends on the fence line staying intact; the line
  // count here never actually changes, but keeping this is one less thing to reason
  // about if that ever stops being true).
  adminBlockUpdateGenerateGraphVisibility(block);
  adminBlockAutoGrow(textarea);
});

// Dragging a <textarea>'s own bottom-right corner (CSS `resize: vertical`, still set in
// admin_base.html) only ever worked on desktop -- iOS Safari has never implemented that
// native resize handle at all, on any site, regardless of the `resize` CSS property, so
// there was simply no way to make a block's textarea taller on a touchscreen (reported
// live: "on iOS how can I expand the text area?"). Auto-growing it to fit its own
// content removes the need to manually resize at all, on any device -- it just gets
// taller as you type more, rather than scrolling internally. Dragging still works on
// desktop for making a block taller than its content needs (e.g. leaving room to paste
// something in), auto-grow doesn't fight it either way -- if a manually-enlarged box's
// content shrinks (e.g. text deleted), the next keystroke recalculates and can shrink it
// back down, same as it grows.
//
// Measuring requires collapsing the box to `height: auto` first, which for a long block
// momentarily makes the whole page much shorter -- the browser clamps the page's scroll
// position to fit, and restoring the height a moment later doesn't undo that clamp. The
// visible effect (reported live) was that with a long matplotlib block scrolled so the
// line being edited sat mid-screen, the first keystroke yanked that line down to the
// bottom of the viewport. Pinning the page's min-height to its current height for the
// duration of the measurement means the page never gets shorter, so there's nothing for
// the browser to clamp in the first place (restoring the scroll afterwards alone wasn't
// enough -- reported live as the jump persisting); the scroll restore stays as a
// backstop. All synchronous, so none of it ever paints.
function adminBlockAutoGrow(textarea) {
  const root = document.documentElement;
  const scrollX = window.scrollX;
  const scrollY = window.scrollY;
  const previousMinHeight = root.style.minHeight;
  root.style.minHeight = `${root.scrollHeight}px`;
  textarea.style.height = "auto";
  textarea.style.height = `${textarea.scrollHeight}px`;
  root.style.minHeight = previousMinHeight;
  if (window.scrollX !== scrollX || window.scrollY !== scrollY) {
    window.scrollTo(scrollX, scrollY);
  }
}

document.addEventListener("input", (event) => {
  const block = event.target.closest(".admin-block");
  if (block && event.target.tagName === "TEXTAREA") {
    adminBlockUpdateGenerateGraphVisibility(block);
    adminBlockAutoGrow(event.target);
  }
});

function adminBlockSwitchToEdit(block) {
  block.dataset.mode = "edit";
  adminBlockSetToggleLabel(block, "Done");
  const textarea = block.querySelector("textarea");
  textarea.focus();
  adminBlockAutoGrow(textarea);
}

// Every block that starts the page already in edit mode (a brand new post's first
// paragraph, or one re-shown mid-edit after a validation error) needs the same sizing
// applied once up front -- the two call sites above only ever fire on a later
// interaction (typing, or switching a block into edit mode after the page has loaded).
document.querySelectorAll('.admin-block[data-mode="edit"] textarea').forEach(adminBlockAutoGrow);

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
      adminBlockSetToggleLabel(block, "Edit");
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
  // toggling a details block open/closed again, a link, an image) -- those clicks bubble
  // up here the same as any other click in the view pane, and should do their own native
  // thing rather than being read as "enter edit mode" (render.expand_details_blocks
  // starts every details block open specifically to avoid needing this click in the
  // first place, but the native toggle remains clickable regardless of its initial
  // state). Formulas are deliberately NOT excluded here (an earlier version excluded
  // .katex too, so a tap could zoom it via katex-zoom.js) -- reported live as "I miss
  // having the block turn editable when clicking on it," since posts are full of math
  // and every click on a formula silently zoomed instead of opening the block. Zooming
  // math while editing is now a click on the block's own header buttons instead (see
  // admin_form.html); katex-zoom.js skips its own tap-to-zoom handling inside
  // .admin-block__view for the same reason, so the two features don't compete again.
  const view = event.target.closest(".admin-block__view");
  if (view && !event.target.closest("summary, a, button, img")) {
    const block = view.closest(".admin-block");
    if (block.dataset.mode === "view") {
      adminBlockEnterEditMode(block);
    }
  }
});
