import render


def test_render_markdown_basic_html():
    html, toc = render.render_markdown("# Title\n\nSome **bold** text.")
    assert "<strong>bold</strong>" in html
    assert toc[0]["name"] == "Title"


def test_arithmatex_normalizes_dollar_delimiters():
    html, _ = render.render_markdown(r"Inline $x^2$ math.")
    assert 'class="arithmatex"' in html
    assert r"\(x^2\)" in html


def test_admonition_and_details_blocks_render():
    text = (
        '!!! question "Problem"\n'
        "    A problem statement.\n\n"
        '??? success "Solution"\n'
        "    The answer.\n"
    )
    html, _ = render.render_markdown(text)
    assert 'class="admonition question"' in html
    assert "<details" in html and 'class="success"' in html


def test_split_excerpt_with_marker():
    excerpt, full = render.split_excerpt("Intro.\n\n<!-- more -->\n\nBody.")
    assert excerpt == "Intro."
    assert "Body." in full
    assert "<!-- more -->" not in full


def test_split_excerpt_without_marker_returns_whole_text_twice():
    excerpt, full = render.split_excerpt("Just one paragraph.")
    assert excerpt == full == "Just one paragraph."


def test_secondary_toc_unwraps_single_root_heading():
    toc_tokens = [
        {
            "level": 1, "id": "welcome", "name": "Welcome",
            "children": [
                {"level": 2, "id": "a", "name": "A", "children": []},
                {"level": 2, "id": "b", "name": "B", "children": []},
            ],
        }
    ]
    result = render.secondary_toc(toc_tokens)
    assert [t["id"] for t in result] == ["a", "b"]


def test_secondary_toc_handles_no_headings():
    assert render.secondary_toc([]) == []


def test_reading_time_minimum_one_minute():
    assert render.reading_time_minutes("<p>short</p>") == 1


def test_reading_time_scales_with_word_count():
    html = "<p>" + " word" * 1000 + "</p>"
    assert render.reading_time_minutes(html) > 1
