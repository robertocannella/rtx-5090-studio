import pytest
from fastapi.testclient import TestClient

import admin_auth
import app as app_module
import db
from app import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_home_page_renders_material_chrome(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Math Notes" in resp.text
    assert 'class="md-header"' in resp.text
    assert "assets/stylesheets/main." in resp.text


def test_katex_zoom_controls_render_on_public_and_admin_pages(client):
    # Same base.html chrome on both -- one zoom preference should reach a public post's
    # rendered math and the admin editor's view-mode preview panes alike.
    post_id = db.create_post("Zoom Control Post", "Meta", "Body.")
    for path in ("/", f"/blog/{db.get_post(post_id=post_id)['slug']}/", "/admin/", "/admin/new"):
        resp = client.get(path)
        assert resp.status_code == 200
        assert "data-katex-zoom-in" in resp.text
        assert "data-katex-zoom-out" in resp.text
        assert "/javascripts/katex-zoom.js" in resp.text


def test_admin_nav_guard_js_loads_on_every_page_before_bundle_js(client):
    # Material's instant-loading (bundle.js) treats every same-origin link click as an
    # AJAX content swap instead of a real page load, including into/out of/between admin
    # pages -- which admin-blocks.js was never designed to survive (its top-level `const`s
    # throw a fatal "already been declared" SyntaxError the second time they run in the
    # same un-reloaded JS scope; reported live via a browser console screenshot). The fix
    # has to be present on every page, public and admin alike, since the click that needs
    # intercepting can originate from either side of that transition -- and it has to load
    # before bundle.js specifically so its capture-phase listener is already registered
    # (capture-phase listeners run before bubble-phase ones regardless of load order, but
    # only once actually attached) by the time bundle.js's own click handler could fire.
    post_id = db.create_post("Nav Guard Post", "Meta", "Body.")
    for path in ("/", f"/blog/{db.get_post(post_id=post_id)['slug']}/", "/admin/", "/admin/new"):
        resp = client.get(path)
        assert resp.status_code == 200
        guard_pos = resp.text.find("/javascripts/admin-nav-guard.js")
        bundle_pos = resp.text.find("bundle.d7400e89.min.js")
        assert guard_pos != -1
        assert bundle_pos != -1
        assert guard_pos < bundle_pos


def test_admin_nav_guard_js_forces_real_navigation_around_admin_pages(client):
    resp = client.get("/javascripts/admin-nav-guard.js")
    assert resp.status_code == 200
    assert "{ capture: true }" in resp.text  # must win the race against bundle.js's own listener
    assert "stopImmediatePropagation" in resp.text
    assert 'pathname.startsWith("/admin/")' in resp.text


def test_admin_blocks_js_survives_being_executed_twice_in_the_same_scope(client):
    # The direct regression test for the reported bug: before this, a second execution of
    # this exact file in one JS global scope (what an instant-nav swap does, absent the
    # guard above) threw a fatal SyntaxError on the *first* line, before a single line of
    # the file ran -- silently leaving the block editor's click/keydown handling never
    # wired up for that page. An IIFE wrapper plus a `window` flag makes a second run a
    # harmless no-op instead.
    resp = client.get("/javascripts/admin-blocks.js")
    assert resp.status_code == 200
    assert "window.__adminBlocksLoaded" in resp.text
    assert resp.text.strip().startswith("//")  # still a classic script, not type="module"


def test_katex_zoom_js_supports_tapping_a_formula_to_zoom(client):
    # Right half of a rendered formula zooms in, left half zooms out -- in addition to
    # the header A-/A+ buttons -- and a tap on the copy-LaTeX button must never also
    # count as a formula tap (see katex-zoom.js's click handler). Formula-tap-to-zoom is
    # skipped inside the admin block editor's own view panes, though (see the next test)
    # -- there, a click on a formula is how you start editing that block.
    resp = client.get("/javascripts/katex-zoom.js")
    assert resp.status_code == 200
    assert "isRightHalf" in resp.text
    assert ".katex-copy" in resp.text
    assert '".admin-block__view"' in resp.text


def test_admin_block_click_to_edit_is_not_hijacked_by_formula_zoom(client):
    # An earlier version excluded .katex from the admin block editor's "click the
    # rendered view to start editing" trigger, so tapping a formula zoomed it instead of
    # opening the block for editing -- reported live as "I miss having the block turn
    # editable when clicking on it." Formulas must NOT be excluded here any more.
    admin_js = client.get("/javascripts/admin-blocks.js")
    assert admin_js.status_code == 200
    assert '"summary, a, button, img"' in admin_js.text
    assert '"summary, a, button, img, .katex"' not in admin_js.text


def test_admin_block_header_has_its_own_zoom_buttons(client):
    # Zoom moved out of tap-on-formula (see above) and into each block's own header, next
    # to Generate graph/Edit/move/delete -- reuses the same data-katex-zoom-in/-out
    # attributes the site header's buttons already use, so katex-zoom.js needed no
    # changes to pick these up too.
    post_id = db.create_post("Zoom Buttons Post", "Meta", "Body.")
    resp = client.get(f"/admin/{post_id}/edit")
    assert resp.status_code == 200
    assert "data-katex-zoom-in" in resp.text
    assert "data-katex-zoom-out" in resp.text
    # Site header (1) + this post's one segment (1) + the hidden "+ Add block" template
    # for brand-new blocks (1) -- all three get their own zoom buttons.
    assert resp.text.count("data-katex-zoom-in") >= 3


def test_katex_zoom_buttons_use_a_magnifying_glass_icon_not_text_glyphs(client):
    # Plain "A-"/"A+" (site header) and bare "-"/"+" (admin block controls) read as more
    # math on a page already full of formulas -- reported live as "a bit confusing."
    # Both locations now use the same magnifying-glass-with-plus/minus SVG icon instead.
    post_id = db.create_post("Zoom Icon Post", "Meta", "Body.")
    for path in ("/", f"/admin/{post_id}/edit"):
        resp = client.get(path)
        assert resp.status_code == 200
        assert "A&minus;" not in resp.text
        assert "A&plus;" not in resp.text
        # The distinctive magnifying-glass-handle path prefix shared by both icons
        # (magnify-plus-outline/magnify-minus-outline) -- unique among this page's icons.
        assert resp.text.count("M15.5,14") >= 2


def test_admin_block_controls_also_appear_below_the_textarea(client):
    # Editing a long block can scroll the header row (with Done/zoom/etc.) out of view --
    # a second copy right below the textarea keeps them reachable without scrolling back
    # up. Both admin_form.html's loop (existing segments) and its <template> (brand-new
    # "+ Add block" blocks) get one each.
    post_id = db.create_post("Footer Controls Post", "Meta", "Body.")
    resp = client.get(f"/admin/{post_id}/edit")
    assert resp.status_code == 200
    assert resp.text.count('class="admin-block__footer"') == 2  # this post's segment + the template
    # Each .admin-block__footer carries the exact same controls as the header: toggle,
    # move up/down, delete, zoom -- not a stripped-down subset.
    footer_start = resp.text.find('class="admin-block__footer"')
    # Window widened from 700 -- the two zoom buttons' inline SVG path data (magnifying-
    # glass icons) is longer than the text glyphs it replaced.
    footer_html = resp.text[footer_start:footer_start + 1500]
    assert "admin-block__toggle" in footer_html
    assert "admin-block__move-up" in footer_html
    assert "admin-block__move-down" in footer_html
    assert "admin-block__delete" in footer_html
    assert "data-katex-zoom-in" in footer_html


def test_admin_blocks_js_updates_both_toggle_and_generate_graph_copies(client):
    # A plain querySelector would only ever find/update the first of the two copies
    # (header, footer) -- both toggle-label and generate-graph-visibility updates must
    # use querySelectorAll instead, or the footer copy would show stale state.
    resp = client.get("/javascripts/admin-blocks.js")
    assert resp.status_code == 200
    assert 'querySelectorAll(".admin-block__toggle")' in resp.text
    assert 'querySelectorAll(".admin-block__generate-graph")' in resp.text


def test_admin_blocks_js_auto_grows_textareas(client):
    # iOS Safari has never implemented the native drag-to-resize corner handle for a
    # <textarea>, regardless of the `resize` CSS property -- reported live as "on iOS how
    # can I expand the text area?" Auto-growing it to fit its own content on every
    # keystroke removes the need to manually resize at all, on any device.
    resp = client.get("/javascripts/admin-blocks.js")
    assert resp.status_code == 200
    assert "function adminBlockAutoGrow(textarea)" in resp.text
    assert "textarea.scrollHeight" in resp.text
    # Wired on typing, on switching a block into edit mode, and once up front for any
    # block that starts the page already in edit mode -- not just one of the three.
    assert "adminBlockAutoGrow(event.target)" in resp.text
    assert "adminBlockAutoGrow(textarea)" in resp.text
    assert ".forEach(adminBlockAutoGrow)" in resp.text


def test_admin_blocks_js_auto_grow_preserves_page_scroll(client):
    # Collapsing the textarea to height:auto to measure it shrinks the page and clamps the
    # scroll position -- reported live as the edited line jumping to the bottom of the
    # screen on the first keystroke. The scroll position must be restored after measuring.
    resp = client.get("/javascripts/admin-blocks.js")
    body = resp.text[resp.text.index("function adminBlockAutoGrow(textarea)"):]
    body = body[:body.index("\n}\n")]
    assert "const scrollY = window.scrollY;" in body
    assert "window.scrollTo(scrollX, scrollY)" in body
    assert "root.style.minHeight = `${root.scrollHeight}px`;" in body


def test_local_assets_are_versioned_per_deploy(client):
    # Plain ETag/Last-Modified lets browsers keep a stale script after a deploy.
    import app as app_module
    v = app_module.templates.env.globals["asset_v"]
    resp = client.get("/blog/")
    assert f'/stylesheets/extra.css?v={v}"' in resp.text
    assert f'/javascripts/print.js?v={v}"' in resp.text


def test_admin_blocks_js_toggles_python_comments_in_matplotlib_blocks_only(client):
    # Ctrl+/ (or Cmd+/) toggles a "# " line-comment prefix -- but only inside a block
    # that currently looks like a matplotlib block (real Python, where "#" is an
    # unambiguous comment syntax). Markdown/LaTeX prose has no equivalent single-
    # character comment convention, so this is deliberately gated on the same
    # matplotlib-fence check the Generate graph button already uses, not wired up
    # unconditionally for every block.
    resp = client.get("/javascripts/admin-blocks.js")
    assert resp.status_code == 200
    assert "function adminBlockToggleComment(textarea)" in resp.text
    assert 'event.key !== "/"' in resp.text
    assert "event.ctrlKey || event.metaKey" in resp.text
    assert "ADMIN_BLOCKS_MATPLOTLIB_FENCE_RE.test(textarea.value)" in resp.text


def test_admin_textarea_keeps_native_scroll_as_a_fallback_to_auto_grow(client):
    # A first version set overflow-y: hidden alongside auto-grow, purely to avoid a
    # cosmetic scrollbar flash -- but that left no fallback at all for any case
    # auto-grow doesn't perfectly cover (paste, autofill, arrow-key cursor movement),
    # reported live as "I can no longer scroll within an edit segment." Native scroll
    # must stay available -- overflow-y must NOT be forced to hidden.
    resp = client.get("/admin/new")
    assert resp.status_code == 200
    # The semicolon distinguishes an actual CSS declaration from this test's own name
    # and the explanatory comment in admin_base.html mentioning the phrase as prose.
    assert "overflow-y: hidden;" not in resp.text


def test_admin_form_widened_to_match_the_sites_own_content_column(client):
    # Was a much narrower, arbitrary 700px -- cramped for a block's textarea, a
    # matplotlib code block especially. 61rem matches Material's own .md-grid
    # max-width elsewhere on the site, not a second arbitrary number.
    resp = client.get("/admin/new")
    assert resp.status_code == 200
    assert "max-width: 61rem;" in resp.text
    assert "max-width: 700px" not in resp.text


def test_admin_action_buttons_share_a_consistent_width(client):
    # Edit/View live/Delete (admin_view.html) each auto-sized to their own text against
    # Material's fixed button padding, so "Edit" and "Delete" were visibly narrower than
    # "View live" -- reported live as "the UI is a bit off." Two earlier attempts:
    # (1) a shared min-width (only a floor -- "View live" could still land wider), then
    # (2) flex: 1 on .admin-actions' direct children, which for Delete meant its <form>
    # wrapper -- Delete then came out *smaller* than the other two, since giving the
    # form flex:1 didn't reliably override its own shrink-to-fit content sizing. Fixed by
    # making the form invisible to layout (display: contents) so its <button> becomes a
    # real, direct flex item of .admin-actions -- sized by its own flex: 1 exactly like
    # Edit/View live's plain <a> tags, not indirectly through a wrapper that has to be
    # coaxed into passing its sizing down.
    post_id = db.create_post("Button Sizing Post", "Meta", "Body.")
    resp = client.get(f"/admin/{post_id}")
    assert resp.status_code == 200
    assert ".admin-actions form {" in resp.text
    assert "display: contents" in resp.text
    assert ".admin-actions .md-button {" in resp.text
    assert "flex: 1" in resp.text


def test_article_text_and_headings_use_the_tuned_sizes(client):
    # Reported live as "the plain text is tiny" and "###heading gets a bit too small",
    # while h1/h2 were already fine -- the base .md-typeset size grows (which h3/h4/body
    # text all scale from in em), but h1/h2 are pinned back to their own previous
    # absolute size so they don't move at all (see extra.css's comment).
    resp = client.get("/stylesheets/extra.css")
    assert resp.status_code == 200
    assert ".md-typeset {\n  font-size: 1.05rem;\n}" in resp.text
    assert ".md-typeset h1 {\n  font-size: 1.8rem;\n}" in resp.text
    assert ".md-typeset h2 {\n  font-size: 1.40625rem;\n}" in resp.text
    # Material hardcodes admonitions/details (!!! question "Problem", etc.) to an
    # absolute 0.64rem, not an em relative to .md-typeset's own size -- reported live as
    # "the text within these blocks [is] tiny" even after the bump above, since that
    # bump alone never reaches an absolute value. Content here is core reading material
    # (problem/solution bodies), so it's pinned to match the surrounding article text.
    assert ".md-typeset .admonition,\n.md-typeset details {\n  font-size: 1.05rem;\n}" in resp.text


def test_katex_zoom_hover_indicator_script_and_style_are_served(client):
    # A faint -/+ near a formula's own edge previews which half a tap would zoom --
    # mouse/trackpad only (see extra.css's hover/pointer media query), driven by two
    # classes katex-zoom.js toggles on mousemove/mouseout.
    js_resp = client.get("/javascripts/katex-zoom.js")
    assert js_resp.status_code == 200
    assert "katex-zoom-hover--left" in js_resp.text
    assert "katex-zoom-hover--right" in js_resp.text

    css_resp = client.get("/stylesheets/extra.css")
    assert css_resp.status_code == 200
    assert "katex-zoom-hover--left" in css_resp.text
    assert "hover: hover" in css_resp.text


def test_katex_copy_button_script_and_style_are_served(client):
    # The actual copy behavior (reading KaTeX's own embedded LaTeX annotation, writing to
    # the clipboard) only runs in a real browser -- this just confirms the pieces it
    # depends on are actually wired up and reachable.
    js_resp = client.get("/javascripts/katex.js")
    assert js_resp.status_code == 200
    assert "mnInjectKatexCopyButtons" in js_resp.text
    assert "application/x-tex" in js_resp.text

    css_resp = client.get("/stylesheets/extra.css")
    assert css_resp.status_code == 200
    assert ".katex-copy" in css_resp.text
    assert "--md-clipboard-icon" in css_resp.text


def test_palette_scope_is_pinned_to_site_root_on_every_page(client):
    # __md_scope must resolve the same way regardless of which page happens to load it,
    # otherwise the palette (dark/light) preference and other persisted UI state end up
    # keyed differently per page -- see base.html's comment for the full explanation.
    db.create_post("Scope Test", "Meta", "Body.")
    for path in ("/", "/blog/", "/blog/scope-test/", "/latex-guide/", "/admin/"):
        resp = client.get(path)
        assert '__md_scope=new URL("/",location)' in resp.text, path


def test_latex_guide_page_renders_markdown_and_katex(client):
    resp = client.get("/latex-guide/")
    assert resp.status_code == 200
    assert "LaTeX Guide" in resp.text
    assert 'class="arithmatex"' in resp.text
    assert "\\frac{1}{2}" in resp.text


def test_latex_guide_python_example_actually_renders_highlighted_not_literal(client):
    # The doc's other code examples are deliberately wrapped in an outer 4-backtick
    # fence so the literal ```name="..."``` syntax shows up as plain text to copy --
    # right, for a worked example of matplotlib syntax, wrong here: that same wrapping
    # was first used for this section too, which meant the one example meant to show off
    # real syntax highlighting rendered as a flat, uncolored box with the ```python
    # fence markers still visible as literal text (caught from a live screenshot). This
    # example must stay unwrapped so it's actually tokenized.
    resp = client.get("/latex-guide/")
    assert resp.status_code == 200
    assert 'class="highlight"' in resp.text
    assert '<span class="k">def</span>' in resp.text
    assert '<span class="nf">distance</span>' in resp.text


def test_matplotlib_guide_nav_tab_appears_on_public_pages(client):
    resp = client.get("/")
    assert 'href="/matplotlib-guide/"' in resp.text
    assert ">Matplotlib Guide<" in resp.text


def test_matplotlib_guide_page_renders_the_full_reference(client):
    resp = client.get("/matplotlib-guide/")
    assert resp.status_code == 200
    assert "<h1" in resp.text and "Matplotlib Guide" in resp.text
    assert 'name="projectile-trajectory"' in resp.text
    assert 'name="distance-with-final-point"' in resp.text  # marking a specific point
    assert "ax.annotate" in resp.text
    assert 'name="distance-with-sample-points"' in resp.text  # labeling several points
    assert "ax.scatter(t_samples, x_samples" in resp.text
    assert "zip(t_samples, x_samples)" in resp.text
    assert 'name="distance-and-velocity"' in resp.text  # plotting two y-variables together
    assert "sharex=True" in resp.text
    assert 'name="two-runners"' in resp.text
    assert "ax.legend()" in resp.text
    assert 'name="freefall-displacement-and-velocity"' in resp.text  # two series, one panel, labeled
    assert "ax.axhline(0" in resp.text
    assert 'name="latex-labels"' in resp.text  # LaTeX/mathtext in labels
    assert 'name="axvline-vs-vlines"' in resp.text  # axes-fraction vs data-coordinate lines
    assert 'name="falling-from-a-height"' in resp.text  # vertical diagram


def test_matplotlib_guide_page_is_not_admin_only(client):
    # Unlike the admin editor's compact Matplotlib tab (gated by show_matplotlib_help),
    # this is a real public nav page -- reachable and identical for every visitor.
    resp = client.get("/matplotlib-guide/")
    assert resp.status_code == 200
    assert "is_admin" not in resp.text  # sanity: never leaks template variable names raw


def test_admin_matplotlib_panel_still_has_no_page_heading(client):
    # The admin side-panel's copy of this content and the public page's copy come from
    # the same source file -- the public page gets its own "Matplotlib Guide" <h1>
    # prepended (see app.py's lifespan), the compact admin panel does not, since it
    # already sits under a "Matplotlib" tab label and has no room to spare.
    db.create_post("Some Post", "Meta", "Body.")
    resp = client.get("/admin/new")
    assert resp.status_code == 200
    idx = resp.text.find('data-panel-pane="matplotlib"')
    pane_start = resp.text.find(">", idx) + 1
    pane_html = resp.text[pane_start:pane_start + 200]
    assert "<h1" not in pane_html


def test_search_index_includes_matplotlib_guide(client):
    resp = client.get("/search/search_index.json")
    assert resp.status_code == 200
    locations = {d["location"] for d in resp.json()["docs"]}
    assert "matplotlib-guide/" in locations


def test_blog_index_empty(client):
    resp = client.get("/blog/")
    assert resp.status_code == 200
    assert "No posts" in resp.text


def test_blog_index_lists_created_post(client):
    db.create_post("My First Post", "Physics", "Intro.\n\n<!-- more -->\n\nBody.")
    resp = client.get("/blog/")
    assert resp.status_code == 200
    assert "My First Post" in resp.text
    assert "Physics" in resp.text
    assert "Intro." in resp.text
    assert "Body." not in resp.text  # index shows the excerpt, not the full post


def test_blog_index_dividers_only_between_posts(client):
    db.create_post("Post One", "Physics", "One.")
    db.create_post("Post Two", "Physics", "Two.")
    db.create_post("Post Three", "Physics", "Three.")
    resp = client.get("/blog/")
    assert resp.text.count('class="md-post__divider"') == 2


def test_individual_post_page(client):
    db.create_post("My First Post", "Physics", "Intro.\n\n<!-- more -->\n\nFull body text.")
    resp = client.get("/blog/my-first-post/")
    assert resp.status_code == 200
    assert "My First Post" in resp.text
    assert "Full body text." in resp.text
    assert 'class="md-content md-content--post"' in resp.text


def test_individual_post_404_for_unknown_slug(client):
    resp = client.get("/blog/does-not-exist/")
    assert resp.status_code == 404


def test_post_page_has_print_button_and_hide_answers_checkbox(client):
    db.create_post("Printable Post", "Physics", "Body.")
    resp = client.get("/blog/printable-post/")
    assert resp.status_code == 200
    assert 'id="post-print-button"' in resp.text
    assert 'id="post-hide-answers"' in resp.text
    assert "Print / Save as PDF" in resp.text
    assert "Hide answers when printing" in resp.text
    # Screen-only controls -- must never show up on the printed page itself.
    assert '<li class="md-nav__item no-print">' in resp.text


def test_print_js_toggles_hide_answers_class_before_printing(client):
    resp = client.get("/javascripts/print.js")
    assert resp.status_code == 200
    assert "post-print-button" in resp.text
    assert "post-hide-answers" in resp.text
    assert "mn-print-hide-answers" in resp.text
    assert "window.print()" in resp.text


def test_print_css_hides_chrome_and_reveals_collapsed_content(client):
    resp = client.get("/stylesheets/extra.css")
    assert resp.status_code == 200
    assert "@media print" in resp.text
    # Site chrome stripped for print.
    assert ".md-header," in resp.text
    # Collapsed admonitions forced open so their content actually prints.
    assert ".md-typeset details > *:not(summary)" in resp.text
    # A graph's click-to-reveal button/modal unwrapped into plain inline content.
    assert ".plot-widget__modal {" in resp.text
    # The "Hide answers" checkbox's effect. Two selectors, not one -- a ??? success
    # block (what every real Solution actually uses) renders as class="success" alone,
    # with no "admonition" class at all (confirmed by rendering one directly and reading
    # its output; see render.py's admonition vs. pymdownx.details extensions) -- an
    # earlier version only had the .admonition.success selector, which never matched a
    # real Solution block at all, reported live as "the answers ... are still showing
    # up." Both forms must be covered so this can't silently regress the same way again.
    assert "body.mn-print-hide-answers .md-typeset .admonition.success" in resp.text
    assert "body.mn-print-hide-answers .md-typeset details.success" in resp.text


def test_solution_admonition_renders_as_bare_success_class(client):
    # Documents the actual, sometimes-surprising output of pymdownx.details for ???
    # blocks (no "admonition" class, unlike !!!'s non-collapsible <div>) -- the exact
    # fact the print-css test above exists to protect against getting out of sync with
    # again. A real end-to-end check, not just a unit test of render.render_markdown.
    body = '??? success "Solution"\n    The answer is 42.\n'
    db.create_post("Solution Class Post", "Meta", body)
    resp = client.get("/blog/solution-class-post/")
    assert resp.status_code == 200
    assert '<details class="success">' in resp.text


def test_category_page_filters_posts(client):
    db.create_post("Physics Post", "Physics", "Body.")
    db.create_post("Algebra Post", "Algebra", "Body.")
    resp = client.get("/blog/category/physics/")
    assert resp.status_code == 200
    assert "Physics Post" in resp.text
    assert "Algebra Post" not in resp.text


def test_feed_xml_lists_posts(client):
    db.create_post("Feed Post", "Physics", "Body.")
    resp = client.get("/feed.xml")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/rss+xml")
    assert "Feed Post" in resp.text
    assert "<rss" in resp.text


def test_feed_xml_includes_tags_as_extra_category_elements(client):
    # RSS's <category> element is legitimately repeatable per item -- one for the post's
    # real category, plus one more per tag, rather than inventing a separate element.
    db.create_post("Feed Post", "Physics", "Body.", tags="limits, continuity")
    resp = client.get("/feed.xml")
    assert "<category>Physics</category>" in resp.text
    assert "<category>limits</category>" in resp.text
    assert "<category>continuity</category>" in resp.text


def test_search_index_includes_posts(client):
    db.create_post("Searchable Post", "Physics", "Findable body text.")
    resp = client.get("/search/search_index.json")
    assert resp.status_code == 200
    data = resp.json()
    locations = {d["location"] for d in data["docs"]}
    assert "blog/searchable-post/" in locations


def test_search_index_includes_post_tags(client):
    db.create_post("Searchable Post", "Physics", "Findable body text.", tags="limits, continuity")
    resp = client.get("/search/search_index.json")
    data = resp.json()
    doc = next(d for d in data["docs"] if d["location"] == "blog/searchable-post/")
    assert doc["tags"] == ["limits", "continuity"]


def test_tag_page_filters_posts_and_handles_multiword_tags(client):
    # "Constant Acceleration" is exactly the multi-word case that plain .lower()
    # matching would break (a raw space in the URL doesn't equal a dash) -- see
    # app.py's _topic_slug.
    db.create_post("Kinematics Post", "Physics", "Body.", tags="Constant Acceleration")
    db.create_post("Calculus Post", "Physics", "Body.", tags="Limits")
    resp = client.get("/blog/tag/constant-acceleration/")
    assert resp.status_code == 200
    assert "Kinematics Post" in resp.text
    assert "Calculus Post" not in resp.text


def test_tag_page_for_unknown_tag_shows_no_posts(client):
    resp = client.get("/blog/tag/nope/")
    assert resp.status_code == 200
    assert "No posts" in resp.text


def test_post_page_links_to_its_tags(client):
    db.create_post("Tagged Post", "Physics", "Body.", tags="Constant Acceleration, Limits")
    resp = client.get("/blog/tagged-post/")
    assert 'href="/blog/tag/constant-acceleration/"' in resp.text
    assert 'href="/blog/tag/limits/"' in resp.text


def test_categories_panel_lists_all_tags(client):
    db.create_post("Tagged Post", "Physics", "Body.", tags="Limits")
    resp = client.get("/")
    assert 'href="/blog/tag/limits/"' in resp.text


def test_footer_sitemap_lists_nav_pages_categories_and_tags(client):
    db.create_post("Footer Test Post", "Physics", "Body.", tags="Limits")
    resp = client.get("/")
    assert 'class="md-footer-sitemap' in resp.text
    # Every top nav page, plus the RSS feed -- not hardcoded twice, driven by the same
    # nav_tabs every other nav element already uses.
    assert 'href="/">Home</a>' in resp.text
    assert 'href="/blog/">Blog</a>' in resp.text
    assert 'href="/latex-guide/">LaTeX Guide</a>' in resp.text
    assert 'href="/matplotlib-guide/">Matplotlib Guide</a>' in resp.text
    assert 'href="/feed.xml">RSS feed</a>' in resp.text
    assert 'href="/blog/category/physics/">Physics</a>' in resp.text
    assert 'href="/blog/tag/limits/">Limits</a>' in resp.text


def test_footer_sitemap_omits_empty_categories_and_tags_groups(client):
    # No posts at all yet -- no Categories/Tags group should render, just Site links.
    resp = client.get("/")
    assert 'class="md-footer-sitemap' in resp.text
    assert ">Categories<" not in resp.text
    assert ">Tags<" not in resp.text


def test_footer_sitemap_appears_on_admin_pages_too(client):
    resp = client.get("/admin/")
    assert 'class="md-footer-sitemap' in resp.text
    assert 'href="/matplotlib-guide/">Matplotlib Guide</a>' in resp.text


def test_matplotlib_post_renders_button_and_serves_image(client):
    body = (
        '```matplotlib name="test-graph"\n'
        "ax = plt.gca()\n"
        "ax.plot([0, 1], [0, 1])\n"
        "```"
    )
    db.create_post("Graph Post", "Physics", body)
    resp = client.get("/blog/graph-post/")
    assert resp.status_code == 200
    assert 'data-plot="test-graph"' in resp.text
    # A ?v=<mtime> cache-busting suffix is expected (see render_plots._versioned_src).
    assert 'src="/assets/plots/graph-post/test-graph.png?v=' in resp.text

    image_resp = client.get("/assets/plots/graph-post/test-graph.png")
    assert image_resp.status_code == 200
    assert image_resp.headers["content-type"] == "image/png"


def test_matplotlib_post_shows_printed_output_next_to_the_graph(client):
    body = (
        '```matplotlib name="printy-graph"\n'
        'print(f"acceleration = {2.31} m/s^2")\n'
        "ax = plt.gca()\n"
        "ax.plot([0, 1], [0, 1])\n"
        "```"
    )
    db.create_post("Printy Post", "Physics", body)
    resp = client.get("/blog/printy-post/")
    assert resp.status_code == 200
    assert 'class="plot-widget__output"' in resp.text
    assert "acceleration = 2.31 m/s^2" in resp.text


def test_matplotlib_inline_graph_shows_directly_and_is_still_clickable(client):
    body = (
        '```matplotlib name="inline-graph" title="Show inline graph" inline="true"\n'
        "ax = plt.gca()\n"
        "ax.plot([0, 1], [0, 1])\n"
        "```"
    )
    db.create_post("Inline Graph Post", "Physics", body)
    resp = client.get("/blog/inline-graph-post/")
    assert resp.status_code == 200
    assert 'class="plot-widget plot-widget--inline"' in resp.text
    assert 'class="plot-widget__inline-img"' in resp.text
    assert 'data-plot="inline-graph"' in resp.text
    assert "plot-widget__toggle" not in resp.text
    assert 'id="plot-modal-inline-graph"' in resp.text  # click-to-enlarge still works

    image_resp = client.get("/assets/plots/inline-graph-post/inline-graph.png")
    assert image_resp.status_code == 200


def test_plot_modal_js_opens_on_any_data_plot_element(client):
    # Not scoped to .plot-widget__toggle specifically -- an inline="true" graph's image
    # carries the same data-plot attribute a button normally would, with no JS changes
    # of its own needed to open the identical modal.
    resp = client.get("/javascripts/plot-modal.js")
    assert resp.status_code == 200
    assert '.closest("[data-plot]")' in resp.text


def test_print_css_avoids_duplicating_an_inline_graphs_image(client):
    resp = client.get("/stylesheets/extra.css")
    assert resp.status_code == 200
    assert ".plot-widget--inline .plot-widget__modal" in resp.text


def test_two_posts_can_reuse_the_same_graph_name_without_colliding(client):
    # A graph's `name` only has to be unique within one post -- db._render() namespaces
    # every graph under its own post's slug specifically so two unrelated posts can each
    # use the same name without one silently overwriting the other's image.
    body_a = '```matplotlib name="shared" title="Post A"\nax = plt.gca()\nax.plot([0, 1], [0, 1])\n```'
    body_b = '```matplotlib name="shared" title="Post B"\nax = plt.gca()\nax.bar(["x"], [5])\n```'
    db.create_post("First Post", "Meta", body_a)
    db.create_post("Second Post", "Meta", body_b)

    resp_a = client.get("/blog/first-post/")
    resp_b = client.get("/blog/second-post/")
    assert 'src="/assets/plots/first-post/shared.png?v=' in resp_a.text
    assert 'src="/assets/plots/second-post/shared.png?v=' in resp_b.text

    image_a = client.get("/assets/plots/first-post/shared.png")
    image_b = client.get("/assets/plots/second-post/shared.png")
    assert image_a.status_code == 200
    assert image_b.status_code == 200
    assert image_a.content != image_b.content  # genuinely two different images, not one overwriting the other


def test_plot_image_404s_for_unknown_slug(client):
    resp = client.get("/assets/plots/no-such-post/whatever.png")
    assert resp.status_code == 404


def test_vendor_asset_path_traversal_rejected(client):
    # ".." collapses out of static/vendor entirely, down to a real file (src/app.py) --
    # the route must still refuse it, not just rely on the target not existing.
    resp = client.get("/assets/../../app.py")
    assert resp.status_code == 404


def test_admin_list_shows_posts(client):
    db.create_post("Admin Visible", "Meta", "Body.")
    resp = client.get("/admin/")
    assert resp.status_code == 200
    assert "Admin Visible" in resp.text


def test_admin_pages_render_the_real_site_header(client):
    for path in ("/admin/", "/admin/new"):
        resp = client.get(path)
        assert resp.status_code == 200
        assert 'class="md-header"' in resp.text
        assert "assets/stylesheets/main." in resp.text
        assert 'class="admin-header"' in resp.text


def test_matplotlib_quickref_panel_shows_on_new_and_edit_forms_only(client):
    # The block editor (new/edit forms) is where someone would actually want this
    # reference open while typing a ```matplotlib block -- not the read-only list, the
    # read-only saved-post view, or any public page.
    post_id = db.create_post("Some Post", "Meta", "Body.")
    should_have_it = ("/admin/new", f"/admin/{post_id}/edit")
    should_not_have_it = ("/", "/admin/", f"/admin/{post_id}", f"/blog/{db.get_post(post_id=post_id)['slug']}/")

    for path in should_have_it:
        resp = client.get(path)
        assert resp.status_code == 200
        assert 'data-panel-tab="matplotlib"' in resp.text
        assert 'data-panel-pane="matplotlib"' in resp.text
        assert ">Matplotlib<" in resp.text
        assert 'name="projectile-trajectory"' in resp.text  # the worked example
        assert 'name="distance-vs-time"' in resp.text  # common physics plots
        assert 'name="velocity-vs-time"' in resp.text
        assert 'name="distance-and-velocity"' in resp.text  # plotting two y-variables together
        assert 'name="freefall-displacement-and-velocity"' in resp.text  # two series, one panel
        assert 'name="distance-with-final-point"' in resp.text  # marking a specific point
        assert "ax.annotate" in resp.text
        assert 'name="distance-with-sample-points"' in resp.text  # labeling several points
        assert 'name="car-and-obstacle"' in resp.text  # sketching a diagram of the problem
        assert 'ax.axis("off")' in resp.text

    for path in should_not_have_it:
        resp = client.get(path)
        assert resp.status_code == 200
        assert 'data-panel-tab="matplotlib"' not in resp.text


def test_matplotlib_quickref_panel_has_a_clickable_jump_to_list(client):
    # The panel used to be one long scroll with no way to jump straight to a section --
    # reported live as wanting "a toc for the matplotlib that I can click through for the
    # sidebar version". Every ## heading gets its own link here, pointing at the exact
    # same #id each heading already carries in the reference text below (both come from
    # the one shared toc_tokens list render_markdown produces for this content -- no
    # separate id-generation logic to keep in sync).
    resp = client.get("/admin/new")
    assert resp.status_code == 200
    assert "categories-panel__list--toc" in resp.text
    assert '<a href="#showing-a-graph-inline">Showing a graph inline</a>' in resp.text
    assert '<a href="#sketching-a-diagram-of-the-problem">Sketching a diagram of the problem</a>' in resp.text
    # The linked-to heading itself is further down in the very same panel, not just a
    # dangling fragment with nothing on the page to scroll to.
    assert 'id="showing-a-graph-inline"' in resp.text


def test_matplotlib_quickref_panel_survives_form_error_redisplay(client):
    # A duplicate-slug or broken-plot error re-renders admin_form.html directly (not a
    # fresh GET) -- the reference panel needs to still be there mid-error, not just on
    # the initial page load.
    db.create_post("Existing", "Meta", "Body.", slug="dup")
    resp = client.post(
        "/admin/new",
        data={"title": "Other", "category": "Meta", "segments": ["Body."], "slug": "dup"},
    )
    assert resp.status_code == 422
    assert 'data-panel-tab="matplotlib"' in resp.text


def test_categories_panel_tabs_share_one_body_not_independent_popouts(client):
    # Browse and (admin-only) Matplotlib are tabs in *one* shared panel, not two
    # independent toggle+body pairs stacked on top of each other -- a second popout
    # stacked below the first opened too low on the page and ran off the bottom of the
    # viewport (reported live). The JS switches which .categories-panel__pane is visible
    # inside the one shared body rather than resolving a body per toggle.
    db.create_post("Some Post", "Meta", "Body.")
    resp = client.get("/admin/new")
    assert resp.status_code == 200
    assert resp.text.count('id="side-panel__body"') == 1
    assert 'data-panel-pane="browse"' in resp.text
    assert 'data-panel-pane="matplotlib"' in resp.text

    js_resp = client.get("/javascripts/categories-panel.js")
    assert js_resp.status_code == 200
    assert "data-panel-tab" in js_resp.text
    assert "data-panel-pane" in js_resp.text


def test_admin_create_post(client):
    resp = client.post(
        "/admin/new",
        data={"title": "New Post", "category": "Meta", "segments": ["Body text."]},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/admin/"
    assert client.get("/blog/new-post/").status_code == 200


def test_admin_create_post_with_tags(client):
    resp = client.post(
        "/admin/new",
        data={"title": "New Post", "category": "Meta", "tags": "Limits, Continuity", "segments": ["Body text."]},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    post = db.get_post(slug="new-post")
    assert post["tags"] == ["Limits", "Continuity"]


def test_admin_edit_form_prefills_tags_input(client):
    post_id = db.create_post("Tagged", "Meta", "Body.", tags="Limits, Continuity")
    resp = client.get(f"/admin/{post_id}/edit")
    assert 'name="tags" value="Limits, Continuity"' in resp.text


def test_admin_edit_post_updates_tags(client):
    post_id = db.create_post("Editable", "Meta", "Old body.", tags="Limits")
    resp = client.post(
        f"/admin/{post_id}/edit",
        data={"title": "Editable", "category": "Meta", "tags": "Continuity", "segments": ["Old body."]},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    post = db.get_post(post_id=post_id)
    assert post["tags"] == ["Continuity"]


def test_admin_create_duplicate_slug_shows_error(client):
    db.create_post("Existing", "Meta", "Body.", slug="dup")
    resp = client.post(
        "/admin/new",
        data={"title": "Other", "category": "Meta", "segments": ["Body."], "slug": "dup"},
    )
    assert resp.status_code == 422
    assert "already exists" in resp.text


def test_admin_create_broken_plot_shows_error(client):
    resp = client.post(
        "/admin/new",
        data={
            "title": "Bad Plot",
            "category": "Meta",
            "segments": ['```matplotlib name="bad"\nthis is not python(((\n```'],
        },
    )
    assert resp.status_code == 422
    assert "matplotlib block" in resp.text


def test_admin_edit_post_redirects_to_view_mode(client):
    post_id = db.create_post("Editable", "Meta", "Old body.")
    resp = client.post(
        f"/admin/{post_id}/edit",
        data={"title": "Edited", "category": "Meta", "segments": ["New body."]},
        follow_redirects=False,
    )
    # Saving switches the page from edit mode to view mode (a rendered read of exactly
    # what was saved, with a way back into Edit) instead of the listing -- so a run of
    # edits doesn't require navigating back to the list and clicking Edit again each time.
    assert resp.status_code == 303
    assert resp.headers["location"] == f"/admin/{post_id}?saved=1"
    post = db.get_post(post_id=post_id)
    assert post["title"] == "Edited"
    assert "New body." in post["body_html"]


def test_admin_edit_form_shows_one_block_per_segment(client):
    body = 'Intro.\n\n!!! question "Problem"\n    Body.\n\n```matplotlib name="g"\nax = plt.gca()\n```'
    post_id = db.create_post("Blocky", "Meta", body)
    resp = client.get(f"/admin/{post_id}/edit")
    assert resp.status_code == 200
    # +1 for the hidden <template>'s own inert textarea (never submitted -- browsers
    # exclude <template> content from forms, unlike a plain count() of the raw HTML).
    assert resp.text.count('name="segments"') == 3 + 1
    assert "Admonition (question)" in resp.text
    assert "Matplotlib graph" in resp.text
    assert "Paragraph" in resp.text


def test_admin_new_form_starts_with_one_empty_block(client):
    resp = client.get("/admin/new")
    assert resp.status_code == 200
    assert resp.text.count('name="segments"') == 1 + 1  # +1 for the hidden <template>
    assert 'data-mode="edit"' in resp.text


def test_admin_edit_form_marks_populated_blocks_as_view_mode(client):
    post_id = db.create_post("View By Default", "Meta", "Some **bold** text.")
    resp = client.get(f"/admin/{post_id}/edit")
    assert resp.status_code == 200
    assert 'data-mode="view"' in resp.text
    assert '<strong>bold</strong>' in resp.text  # rendered into the block's view pane


def test_admin_preview_segment_renders_markdown(client):
    resp = client.post("/admin/preview-segment", data={"text": "Some **bold** text."})
    assert resp.status_code == 200
    assert "<strong>bold</strong>" in resp.text


def test_admin_preview_segment_renders_admonitions_and_math(client):
    text = '!!! question "Problem"\n    What is $x^2$?'
    resp = client.post("/admin/preview-segment", data={"text": text})
    assert resp.status_code == 200
    assert 'class="admonition question"' in resp.text
    assert 'class="arithmatex"' in resp.text


def test_admin_preview_segment_renders_collapsible_blocks_expanded_by_default(client):
    # ??? blocks render as <details>, collapsed by default on the public site -- the
    # editor's view mode shows them expanded, both so nothing needs manually expanding to
    # review it and because clicking a collapsed block's <summary> to open it would
    # otherwise bubble up as "click the view pane -> enter edit mode".
    text = '??? success "Solution"\n    The answer.'
    resp = client.post("/admin/preview-segment", data={"text": text})
    assert resp.status_code == 200
    assert "<details open" in resp.text


def test_admin_preview_segment_shows_graph_image_directly_not_behind_a_button(client):
    post_id = db.create_post(
        "Graph Preview Post", "Meta",
        '```matplotlib name="preview-visible-test"\nax = plt.gca()\nax.plot([0, 1], [0, 1])\n```',
    )
    post = db.get_post(post_id=post_id)
    resp = client.post("/admin/preview-segment", data={"text": post["body_markdown"], "slug": post["slug"]})
    assert resp.status_code == 200
    assert f'src="/assets/plots/{post["slug"]}/preview-visible-test.png?v=' in resp.text
    assert "plot-widget__toggle" not in resp.text  # not hidden behind a click-to-reveal button


def test_admin_preview_segment_without_slug_shows_placeholder_for_unsaved_graph(client):
    # No slug means "not saved yet" (a brand new post) -- even a name that happens to
    # match some other post's already-saved graph must not accidentally show that image.
    db.create_post(
        "Existing Graph Owner", "Meta",
        '```matplotlib name="shared-name-test"\nax = plt.gca()\nax.plot([0, 1], [0, 1])\n```',
    )
    resp = client.post(
        "/admin/preview-segment",
        data={"text": '```matplotlib name="shared-name-test"\nax = plt.gca()\n```'},
    )
    assert resp.status_code == 200
    assert "will render here after you save" in resp.text


def test_admin_preview_segment_empty_text_returns_empty_body(client):
    resp = client.post("/admin/preview-segment", data={"text": "   "})
    assert resp.status_code == 200
    assert resp.text == ""


def test_admin_preview_segment_never_executes_matplotlib_code(client):
    # A block whose code would raise if actually run -- previewing it (unlike saving it)
    # must never execute it, since this fires on every edit<->view toggle, not just save.
    text = '```matplotlib name="danger"\nraise RuntimeError("must not run")\n```'
    resp = client.post("/admin/preview-segment", data={"text": text})
    assert resp.status_code == 200
    assert "will render here after you save" in resp.text


def test_admin_generate_graph_executes_code_and_serves_the_image(client):
    text = '```matplotlib name="gen-graph-test" title="Show it"\nax = plt.gca()\nax.plot([0, 1], [0, 1])\n```'
    resp = client.post("/admin/generate-graph", data={"text": text})
    assert resp.status_code == 200
    assert 'src="/admin/preview-plots/gen-graph-test.png?v=' in resp.text
    assert "plot-widget__toggle" not in resp.text  # visible directly, not behind a button

    image_resp = client.get("/admin/preview-plots/gen-graph-test.png")
    assert image_resp.status_code == 200
    assert image_resp.headers["content-type"] == "image/png"


def test_admin_generate_graph_never_touches_the_real_saved_image(client):
    # Regenerating a block's graph before saving the post must never change what a live,
    # already-published post's graph looks like -- only an actual save may write there.
    post_id = db.create_post(
        "Real Graph Post", "Meta",
        '```matplotlib name="real-graph"\nax = plt.gca()\nax.plot([0, 1], [0, 1])\n```',
    )
    post = db.get_post(post_id=post_id)
    real_image_path = db.PLOTS_DIR / post["slug"] / "real-graph.png"
    real_image_before = real_image_path.read_bytes()

    edited_text = '```matplotlib name="real-graph"\nax = plt.gca()\nax.bar(["x"], [5])\n```'
    resp = client.post("/admin/generate-graph", data={"text": edited_text})
    assert resp.status_code == 200

    real_image_after = real_image_path.read_bytes()
    assert real_image_after == real_image_before  # untouched by the un-saved preview


def test_admin_generate_graph_shows_error_for_broken_code(client):
    text = '```matplotlib name="broken-gen"\nthis is not valid python(((\n```'
    resp = client.post("/admin/generate-graph", data={"text": text})
    assert resp.status_code == 200
    assert 'class="admin-error"' in resp.text
    assert "broken-gen" in resp.text


def test_admin_generate_graph_empty_text_returns_empty_body(client):
    resp = client.post("/admin/generate-graph", data={"text": "   "})
    assert resp.status_code == 200
    assert resp.text == ""


def test_admin_preview_plot_image_404s_for_unknown_filename(client):
    resp = client.get("/admin/preview-plots/does-not-exist.png")
    assert resp.status_code == 404


def test_preview_plots_dir_tracks_current_plots_dir(monkeypatch, tmp_path):
    # Regression test: _preview_plots_dir() must be computed fresh from db.PLOTS_DIR on
    # every call, not cached once at import time -- a cached version would silently keep
    # pointing at the real default forever after, meaning every test (and every real
    # request, if db.PLOTS_DIR were ever reconfigured) would write generated graphs
    # straight into the live production data directory instead of an isolated one.
    fake_plots_dir = tmp_path / "custom" / "plots"
    monkeypatch.setattr(db, "PLOTS_DIR", fake_plots_dir)
    assert app_module._preview_plots_dir() == fake_plots_dir.parent / "preview_plots"


def test_admin_edit_submit_with_multiple_segments_reassembles_body(client):
    post_id = db.create_post("Multi Block", "Meta", "Original.")
    resp = client.post(
        f"/admin/{post_id}/edit",
        data={
            "title": "Multi Block",
            "category": "Meta",
            "segments": ["Intro paragraph.", '!!! question "Problem"\n    What is x?'],
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    post = db.get_post(post_id=post_id)
    assert post["body_markdown"] == 'Intro paragraph.\n\n!!! question "Problem"\n    What is x?'
    assert "Intro paragraph." in post["body_html"]
    assert 'class="admonition question"' in post["body_html"]


def test_admin_edit_form_has_no_preview(client):
    # The edit FORM itself stays a plain form -- the rendered view lives on its own page
    # (/admin/{id}), not appended below the textarea.
    post_id = db.create_post("Existing Post", "Meta", "Already **saved** body.")
    resp = client.get(f"/admin/{post_id}/edit")
    assert resp.status_code == 200
    assert 'class="admin-preview' not in resp.text


def test_admin_view_page_shows_rendered_post_and_actions(client):
    post_id = db.create_post("View Mode Post", "Meta", "Some **bold** body.")
    resp = client.get(f"/admin/{post_id}")
    assert resp.status_code == 200
    assert "<strong>bold</strong>" in resp.text
    assert f'href="/admin/{post_id}/edit"' in resp.text
    assert 'href="/blog/view-mode-post/"' in resp.text
    assert f'action="/admin/{post_id}/delete"' in resp.text
    assert "Saved." not in resp.text  # no ?saved=1 on a plain visit


def test_admin_view_page_has_all_posts_link_in_sidebar_not_header(client):
    post_id = db.create_post("Sidebar Link Post", "Meta", "Body.")
    resp = client.get(f"/admin/{post_id}")
    assert resp.status_code == 200
    assert '<div class="admin-header">' in resp.text
    header_section = resp.text.split('<div class="admin-header">')[1].split("</div>")[0]
    assert "All posts" not in header_section
    assert '<span class="md-ellipsis">All posts</span>' in resp.text


def test_admin_list_still_shows_all_posts_link_in_its_own_header(client):
    resp = client.get("/admin/")
    assert resp.status_code == 200
    header_section = resp.text.split('<div class="admin-header">')[1].split("</div>")[0]
    assert "All posts" in header_section


def test_admin_new_form_has_no_all_posts_link_in_header(client):
    # The Cancel link in the form's own action row already goes back to the list --
    # showing All posts in the header too was redundant.
    resp = client.get("/admin/new")
    assert resp.status_code == 200
    header_section = resp.text.split('<div class="admin-header">')[1].split("</div>")[0]
    assert "All posts" not in header_section


def test_admin_edit_form_has_no_all_posts_link_in_header(client):
    post_id = db.create_post("No Header Link Post", "Meta", "Body.")
    resp = client.get(f"/admin/{post_id}/edit")
    assert resp.status_code == 200
    header_section = resp.text.split('<div class="admin-header">')[1].split("</div>")[0]
    assert "All posts" not in header_section


def test_admin_view_page_shows_saved_banner_after_redirect(client):
    post_id = db.create_post("Saved Banner Post", "Meta", "Body.")
    resp = client.get(f"/admin/{post_id}?saved=1")
    assert resp.status_code == 200
    assert "Saved." in resp.text


def test_admin_view_nonexistent_post_404s(client):
    resp = client.get("/admin/9999")
    assert resp.status_code == 404


def test_admin_new_post_still_redirects_to_listing(client):
    # Only editing an existing post switches to view mode -- creating a brand new post
    # still goes to the listing, since there's no "keep iterating on this one" context yet.
    resp = client.post(
        "/admin/new",
        data={"title": "Fresh Post", "category": "Meta", "segments": ["Body."]},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/admin/"


def test_admin_delete_post(client):
    post_id = db.create_post("Deletable", "Meta", "Body.")
    resp = client.post(f"/admin/{post_id}/delete", follow_redirects=False)
    assert resp.status_code == 303
    assert db.get_post(post_id=post_id) is None


def test_admin_edit_nonexistent_post_404s(client):
    resp = client.get("/admin/9999/edit")
    assert resp.status_code == 404


def test_anonymous_visitor_does_not_see_admin_nav_or_edit_link(client):
    post_id = db.create_post("Anon View", "Meta", "Body.")
    home = client.get("/")
    assert ">Admin<" not in home.text
    post = client.get("/blog/anon-view/")
    assert f'href="/admin/{post_id}/edit"' not in post.text


def test_anonymous_visitor_sees_a_login_link_to_admin(client):
    # There's no real login form to submit -- Caddy's basic_auth in front of /admin/* is
    # the actual gate (see admin_auth.py) -- this link just gets the site owner to that
    # prompt without needing to remember or type the URL. Must disappear once the cosmetic
    # admin cookie is set, same as the "Admin" nav item it's standing in for.
    home = client.get("/")
    assert '>Login<' in home.text
    assert 'href="/admin/" class="md-tabs__link">Login<' in home.text

    client.cookies.set(admin_auth.COOKIE_NAME, admin_auth.make_cookie_value())
    home = client.get("/")
    assert ">Login<" not in home.text


def test_visiting_admin_sets_the_admin_cookie(client):
    resp = client.get("/admin/")
    assert admin_auth.COOKIE_NAME in resp.cookies


def test_admin_cookie_makes_admin_nav_and_edit_link_visible_on_public_pages(client):
    post_id = db.create_post("Cookie View", "Meta", "Body.")
    client.cookies.set(admin_auth.COOKIE_NAME, admin_auth.make_cookie_value())
    home = client.get("/")
    assert ">Admin<" in home.text
    post = client.get("/blog/cookie-view/")
    assert f'href="/admin/{post_id}/edit"' in post.text


def test_forged_admin_cookie_does_not_grant_admin_visibility(client):
    client.cookies.set(admin_auth.COOKIE_NAME, "9999999999.not-a-real-signature")
    home = client.get("/")
    assert ">Admin<" not in home.text


def test_expired_admin_cookie_does_not_grant_admin_visibility(client):
    # A correctly-signed value (using the module's real signing function, not a guess)
    # but with an expiry timestamp in the past -- must be rejected on expiry, not just
    # on a bad signature.
    expired_at = "1"
    expired_cookie = f"{expired_at}.{admin_auth._sign(expired_at)}"
    client.cookies.set(admin_auth.COOKIE_NAME, expired_cookie)
    home = client.get("/")
    assert ">Admin<" not in home.text


def test_admin_new_without_draft_token_redirects_to_mint_one(client):
    resp = client.get("/admin/new", follow_redirects=False)
    assert resp.status_code == 303
    location = resp.headers["location"]
    assert location.startswith("/admin/new?draft=")
    token = location.split("draft=")[1]
    assert len(token) == 32  # uuid4().hex


def test_admin_new_with_draft_token_has_the_hidden_draft_key_field(client):
    resp = client.get("/admin/new")  # follows the redirect above automatically
    assert resp.status_code == 200
    assert 'id="admin-draft-key"' in resp.text
    assert 'name="draft_key"' in resp.text
    # No draft has been autosaved yet under this fresh token -- no restore banner.
    assert '<div class="admin-draft-banner">' not in resp.text


def test_admin_draft_endpoint_saves_without_touching_posts(client):
    resp = client.post(
        "/admin/draft",
        data={"key": "new:test-token", "title": "Draft Title", "category": "Physics", "tags": "a, b",
              "segments": ["First block.", "Second block."]},
    )
    assert resp.status_code == 200
    assert resp.json()["saved_at"]
    draft = db.get_draft("new:test-token")
    assert draft["title"] == "Draft Title"
    assert draft["segments"] == ["First block.", "Second block."]
    assert db.list_posts() == []  # definitely never created a real post


def test_admin_draft_endpoint_rejects_a_malformed_key(client):
    resp = client.post("/admin/draft", data={"key": "not-a-real-prefix:x", "title": "x"})
    assert resp.status_code == 400


def test_admin_draft_endpoint_never_executes_matplotlib_code(client):
    # Autosaving must be side-effect-free -- a broken (or even a perfectly valid but
    # slow) matplotlib block sitting in an in-progress draft must never run just because
    # two minutes passed, unlike a real Save.
    broken = '```matplotlib name="x"\nraise RuntimeError("must never run")\n```'
    resp = client.post("/admin/draft", data={"key": "new:anim-token", "title": "t", "category": "c", "segments": [broken]})
    assert resp.status_code == 200  # no PlotError, no 500 -- it was never executed


def test_admin_new_form_restores_a_draft_with_a_banner(client):
    redirect = client.get("/admin/new", follow_redirects=False)
    url_with_token = redirect.headers["location"]
    token = url_with_token.split("draft=")[1]
    db.save_draft(f"new:{token}", "Recovered Title", "Recovered Category", "tagx", ["Recovered body."])

    resp = client.get(url_with_token)
    assert resp.status_code == 200
    assert '<div class="admin-draft-banner">' in resp.text
    assert 'value="Recovered Title"' in resp.text
    assert "Recovered body." in resp.text


def test_admin_edit_form_restores_a_newer_draft_over_the_saved_post(client):
    post_id = db.create_post("Saved Title", "Meta", "Saved body.", tags=["orig"])
    db.save_draft(f"post:{post_id}", "Unsaved Title", "Meta", "orig", ["Unsaved body in progress."])

    resp = client.get(f"/admin/{post_id}/edit")
    assert resp.status_code == 200
    assert '<div class="admin-draft-banner">' in resp.text
    assert "Restored an autosaved draft" in resp.text
    assert 'value="Unsaved Title"' in resp.text
    assert "Unsaved body in progress." in resp.text
    # The real saved post itself must be completely untouched by merely viewing the draft.
    assert db.get_post(post_id=post_id)["title"] == "Saved Title"


def test_admin_edit_form_discard_draft_removes_it_and_shows_saved_content(client):
    post_id = db.create_post("Saved Title", "Meta", "Saved body.")
    db.save_draft(f"post:{post_id}", "Unsaved Title", "Meta", "", ["Unsaved body."])

    resp = client.get(f"/admin/{post_id}/edit?discard_draft=1")
    assert resp.status_code == 200
    assert '<div class="admin-draft-banner">' not in resp.text
    assert 'value="Saved Title"' in resp.text
    assert db.get_draft(f"post:{post_id}") is None


def test_admin_edit_submit_deletes_the_draft_on_a_real_save(client):
    post_id = db.create_post("Original", "Meta", "Body.")
    db.save_draft(f"post:{post_id}", "Unsaved", "Meta", "", ["Unsaved body."])

    client.post(
        f"/admin/{post_id}/edit",
        data={"title": "Updated", "category": "Meta", "segments": ["Updated body."], "draft_key": f"post:{post_id}"},
        follow_redirects=False,
    )
    assert db.get_draft(f"post:{post_id}") is None
    # And the real save used the form's own content, not the stale draft's.
    assert db.get_post(post_id=post_id)["title"] == "Updated"


def test_admin_new_submit_deletes_the_draft_on_a_real_save(client):
    db.save_draft("new:submitted-token", "Draft", "Meta", "", ["Draft body."])
    client.post(
        "/admin/new",
        data={"title": "Real Post", "category": "Meta", "segments": ["Real body."], "draft_key": "new:submitted-token"},
        follow_redirects=False,
    )
    assert db.get_draft("new:submitted-token") is None


def test_admin_autosave_js_is_served_and_included_on_admin_form_pages(client):
    resp = client.get("/javascripts/admin-autosave.js")
    assert resp.status_code == 200
    assert "ADMIN_AUTOSAVE_INTERVAL_MS" in resp.text
    assert "/admin/draft" in resp.text

    post_id = db.create_post("Script Include Post", "Meta", "Body.")
    for path in ("/admin/new", f"/admin/{post_id}/edit"):
        resp = client.get(path)
        assert "/javascripts/admin-autosave.js" in resp.text


def test_admin_autosave_notification_is_a_non_blocking_fading_toast(client):
    # Reported live: wanted "some minor notification during save (that doesn't impede
    # the editing)" -- fixed position + pointer-events: none so it can never sit on top
    # of and intercept a click on the textarea underneath it, and an opacity/transform
    # transition (toggled by admin-autosave.js's admin-autosave-status--visible class)
    # so it fades in and back out on its own rather than permanently occupying space.
    post_id = db.create_post("Toast Post", "Meta", "Body.")
    resp = client.get(f"/admin/{post_id}/edit")
    assert resp.status_code == 200
    assert '<p id="admin-autosave-status" class="admin-autosave-status" aria-live="polite"></p>' in resp.text

    css = client.get("/admin/").text  # admin_base.html's <style> block, same on every admin page
    assert "position: fixed" in css
    assert "pointer-events: none" in css
    assert "admin-autosave-status--visible" in css

    js = client.get("/javascripts/admin-autosave.js").text
    assert "admin-autosave-status--visible" in js
    assert "setTimeout" in js  # auto-dismisses itself, not left on screen indefinitely


def test_admin_autosave_tick_now_is_exposed_for_other_scripts_to_call(client):
    # Reported live: "every time I click done or generate graph, it should save the
    # draft too" -- rather than only ever on the scheduled 2-minute timer. admin-blocks.js
    # calls this after both of those actions finish (see its own adminBlockSwitchToView
    # and the Generate graph click handler); exposing the *same* tick function (not a
    # separate code path) means the usual dirty-check/empty-check guards still apply --
    # calling it when nothing's actually changed is just a harmless no-op either way.
    js = client.get("/javascripts/admin-autosave.js").text
    assert "window.adminAutosaveTickNow = adminAutosaveTick" in js

    blocks_js = client.get("/javascripts/admin-blocks.js").text
    assert blocks_js.count("window.adminAutosaveTickNow?.()") == 2  # Done, and Generate graph
