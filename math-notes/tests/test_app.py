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


def test_katex_zoom_js_supports_tapping_a_formula_to_zoom(client):
    # Right half of a rendered formula zooms in, left half zooms out -- in addition to
    # the header A-/A+ buttons -- and a tap on the copy-LaTeX button must never also
    # count as a formula tap (see katex-zoom.js's click handler).
    resp = client.get("/javascripts/katex-zoom.js")
    assert resp.status_code == 200
    assert "isRightHalf" in resp.text
    assert ".katex-copy" in resp.text

    # The admin block editor's "click the rendered view to start editing" handler must
    # exclude formulas too, so tapping one to zoom doesn't also drop the block into edit
    # mode (see admin-blocks.js).
    admin_js = client.get("/javascripts/admin-blocks.js")
    assert admin_js.status_code == 200
    assert '"summary, a, button, img, .katex"' in admin_js.text


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
    assert 'src="/assets/plots/graph-post/test-graph.png"' in resp.text

    image_resp = client.get("/assets/plots/graph-post/test-graph.png")
    assert image_resp.status_code == 200
    assert image_resp.headers["content-type"] == "image/png"


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
    assert 'src="/assets/plots/first-post/shared.png"' in resp_a.text
    assert 'src="/assets/plots/second-post/shared.png"' in resp_b.text

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
        assert 'data-md-component="matplotlib-help-panel"' in resp.text
        assert ">Matplotlib<" in resp.text
        assert 'name="projectile-trajectory"' in resp.text  # the worked example

    for path in should_not_have_it:
        resp = client.get(path)
        assert resp.status_code == 200
        assert 'data-md-component="matplotlib-help-panel"' not in resp.text


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
    assert 'data-md-component="matplotlib-help-panel"' in resp.text


def test_categories_panel_toggle_scopes_to_its_own_panel(client):
    # Two independent side panels (Browse, Matplotlib) share the same generic
    # .categories-panel/__toggle/__body classes -- the JS must resolve each toggle's own
    # body via its own parent, not a document-wide first-match lookup, or clicking one
    # toggle would open/close the other panel instead.
    resp = client.get("/javascripts/categories-panel.js")
    assert resp.status_code == 200
    assert "toggle.parentElement.querySelector" in resp.text


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
    assert f'src="/assets/plots/{post["slug"]}/preview-visible-test.png"' in resp.text
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
    assert 'src="/admin/preview-plots/gen-graph-test.png"' in resp.text
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
