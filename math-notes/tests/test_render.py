import render


def test_render_markdown_basic_heading_and_paragraph():
    html = render.render_markdown("# Title\n\nHello world.")
    assert "<h1" in html
    assert "Hello world." in html


def test_admonition_block_renders_as_admonition_div():
    html = render.render_markdown('!!! question "Problem"\n    A ball is thrown.')
    assert 'class="admonition question"' in html
    assert "Problem" in html
    assert "A ball is thrown." in html


def test_collapsible_details_block_renders_as_details_element():
    html = render.render_markdown('??? success "Solution"\n    The answer is 42.')
    assert "<details" in html
    assert "success" in html
    assert "The answer is 42." in html


def test_arithmatex_leaves_latex_as_literal_text_for_client_side_katex():
    html = render.render_markdown("The formula $x^2 + y^2 = r^2$ is well known.")
    # generic mode wraps math in a span/div and normalizes $...$ to \(...\), but does not
    # render it server-side -- the raw LaTeX source must still be present, just with
    # normalized delimiters, for KaTeX to find and render in-browser.
    assert "x^2 + y^2 = r^2" in html
    assert "arithmatex" in html
    assert "\\(" in html and "\\)" in html


def test_raw_html_passes_through_via_md_in_html():
    html = render.render_markdown('<div class="plot-widget">\n<p>raw</p>\n</div>')
    assert 'class="plot-widget"' in html


def test_split_excerpt_with_marker():
    excerpt, full = render.split_excerpt("Intro paragraph.\n\n<!-- more -->\n\nRest of post.")
    assert excerpt == "Intro paragraph."
    assert "Rest of post." in full
    assert "<!-- more -->" not in full


def test_split_excerpt_without_marker_uses_whole_post_for_both():
    excerpt, full = render.split_excerpt("Just one paragraph, no marker.")
    assert excerpt == full == "Just one paragraph, no marker."
