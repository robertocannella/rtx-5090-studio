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


def test_split_excerpt_tolerates_a_missing_bang():
    # A missing `!` (`<-- more -->` instead of `<!-- more -->`) is a one-key typo that's
    # easy to make on a touchscreen keyboard's cramped symbol layout -- confirmed live on
    # a real post authored on iOS: the marker went unrecognized entirely, leaving a
    # stray, literal "<-- more -->" visible on the page instead of silently splitting.
    excerpt, full = render.split_excerpt("Intro.\n\n<-- more -->\n\nBody.")
    assert excerpt == "Intro."
    assert "Body." in full
    assert "more" not in full


def test_normalize_display_math_spacing_isolates_tight_bracket_block():
    text = "Intro.\n\\[\nx^2\n\\]\nOutro."
    normalized = render.normalize_display_math_spacing(text)
    html, _ = render.render_markdown(normalized)
    assert 'class="arithmatex"' in html
    assert "<p>[" not in html  # the un-isolated, broken-escaping failure mode


def test_normalize_display_math_spacing_isolates_tight_dollar_block():
    text = "Intro.\n$$\nx^2\n$$\nOutro."
    html, _ = render.render_markdown(render.normalize_display_math_spacing(text))
    assert 'class="arithmatex"' in html


def test_normalize_display_math_spacing_handles_back_to_back_blocks():
    text = "\\[\na\n\\]\n\\[\nb\n\\]"
    html, _ = render.render_markdown(render.normalize_display_math_spacing(text))
    assert html.count('class="arithmatex"') == 2


def test_normalize_display_math_spacing_leaves_already_spaced_text_working():
    text = "Intro.\n\n$$\nx^2\n$$\n\nOutro."
    html, _ = render.render_markdown(render.normalize_display_math_spacing(text))
    assert 'class="arithmatex"' in html
    assert "Intro." in html and "Outro." in html


def test_normalize_display_math_spacing_does_not_touch_inline_math():
    text = "The value $x^2$ is inline."
    assert render.normalize_display_math_spacing(text) == text


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
