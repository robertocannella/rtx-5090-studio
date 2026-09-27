import json
import re
from pathlib import Path

import db
import render

# Exact body_markdown of every real post in the live database, exported verbatim (not
# hand-transcribed -- a manual transcription previously introduced a subtle whitespace
# difference that made a real rendering quirk look like a segmentation bug). See
# fixtures/real_posts.json; re-export with:
#   docker exec -u 1000:1000 -e MATH_NOTES_DB_PATH=/app/data/math-notes.db math-notes \
#     python3 -c "import db, json; print(json.dumps([dict(p) for p in db.list_posts()]))"
REAL_POSTS = json.loads((Path(__file__).parent / "fixtures" / "real_posts.json").read_text())


def _normalize_whitespace(html):
    # join_segments() strips each segment's own leading/trailing whitespace, which can
    # remove a source line's insignificant trailing space right at a tag boundary (e.g.
    # "...collision). </p>" -> "...collision).</p>") -- invisible in a rendered browser
    # either way, since whitespace immediately touching a tag is never significant.
    # Collapse that away entirely (not just runs of it down to one space) before also
    # collapsing ordinary internal whitespace runs, since that's the real correctness
    # bar here, not incidental byte-for-byte identity.
    html = re.sub(r"\s+<", "<", html)
    html = re.sub(r">\s+", ">", html)
    return " ".join(html.split())


def test_split_and_join_roundtrip_renders_identically_for_every_real_post():
    # Compared through db._render() -- the actual pipeline a save goes through (it splits
    # the excerpt marker out and normalizes math spacing before rendering) -- not a bare
    # render.render_markdown() call, which would compare against markdown that production
    # never actually renders as-is (the raw, not-yet-excerpt-split text).
    for post in REAL_POSTS:
        body = post["body_markdown"]
        _, original_html, _, _ = db._render(body)
        segments = render.split_into_segments(body)
        rejoined = render.join_segments(segments)
        _, rejoined_html, _, _ = db._render(rejoined)
        assert _normalize_whitespace(rejoined_html) == _normalize_whitespace(original_html), \
            f"mismatch for {post['slug']}"


def test_split_separates_paragraph_admonition_and_graph():
    text = (
        "Intro paragraph.\n\n"
        '!!! question "Problem"\n'
        "    Body text.\n\n"
        '```matplotlib name="g"\n'
        "ax = plt.gca()\n"
        "```\n"
    )
    segments = render.split_into_segments(text)
    assert len(segments) == 3
    assert segments[0] == "Intro paragraph."
    assert segments[1].startswith('!!! question "Problem"')
    assert "    Body text." in segments[1]
    assert segments[2].startswith('```matplotlib name="g"')


def test_split_keeps_adjacent_admonitions_separate_with_no_blank_line_between():
    text = '!!! question "Problem"\n    Line.\n??? success "Solution"\n    Other line.\n'
    segments = render.split_into_segments(text)
    assert len(segments) == 2
    assert segments[0].startswith('!!! question')
    assert segments[1].startswith('??? success')


def test_split_keeps_internal_blank_lines_inside_one_admonition():
    text = (
        '??? info "Formulas"\n'
        '    $$\n'
        '    a = b\n'
        '    $$\n'
        '\n'
        '    $$\n'
        '    c = d\n'
        '    $$\n'
    )
    segments = render.split_into_segments(text)
    assert len(segments) == 1
    assert "a = b" in segments[0] and "c = d" in segments[0]


def test_split_separates_top_level_math_block_from_paragraphs():
    text = "Before.\n\n$$\nx^2\n$$\n\nAfter."
    segments = render.split_into_segments(text)
    assert segments == ["Before.", "$$\nx^2\n$$", "After."]


def test_split_separates_bracket_math_block():
    text = "Before.\n\n\\[\nx^2\n\\]\n\nAfter."
    segments = render.split_into_segments(text)
    assert segments == ["Before.", "\\[\nx^2\n\\]", "After."]


def test_split_keeps_multiline_paragraph_as_one_segment():
    text = "Line one\nline two\nline three.\n\nNext paragraph."
    segments = render.split_into_segments(text)
    assert segments == ["Line one\nline two\nline three.", "Next paragraph."]


def test_split_separates_excerpt_marker_as_its_own_segment():
    text = "Intro.\n\n<!-- more -->\n\nRest."
    segments = render.split_into_segments(text)
    assert segments == ["Intro.", "<!-- more -->", "Rest."]


def test_split_heading_is_its_own_segment():
    text = "## A heading\n\nParagraph text."
    segments = render.split_into_segments(text)
    assert segments == ["## A heading", "Paragraph text."]


def test_join_segments_strips_and_joins_with_blank_lines():
    assert render.join_segments(["  a  ", "b"]) == "a\n\nb"


def test_join_segments_drops_empty_segments():
    assert render.join_segments(["a", "   ", "b"]) == "a\n\nb"


def test_classify_segment_labels():
    assert render.classify_segment("Just text.") == "Paragraph"
    assert render.classify_segment("## Heading") == "Heading"
    assert render.classify_segment("<!-- more -->") == "Excerpt break"
    assert render.classify_segment('```matplotlib name="g"\ncode\n```') == "Matplotlib graph"
    assert render.classify_segment("```\ncode\n```") == "Code block"
    assert render.classify_segment("$$\nx\n$$") == "Math block"
    assert render.classify_segment("\\[\nx\n\\]") == "Math block"
    assert render.classify_segment('!!! question "Problem"\n    Body.') == "Admonition (question)"
    assert render.classify_segment('??? success "Solution"\n    Body.') == "Collapsible (success)"


def test_expand_details_blocks_adds_open_attribute():
    html = '<details class="success"><summary>Solution</summary><p>Body.</p></details>'
    assert render.expand_details_blocks(html) == (
        '<details open class="success"><summary>Solution</summary><p>Body.</p></details>'
    )


def test_expand_details_blocks_handles_multiple_and_leaves_other_tags_alone():
    html = "<p>Text.</p><details><summary>A</summary></details><details><summary>B</summary></details>"
    result = render.expand_details_blocks(html)
    assert result.count("<details open") == 2
    assert "<p>Text.</p>" in result


def test_expand_details_blocks_noop_on_html_with_no_details():
    html = "<p>Just a paragraph.</p>"
    assert render.expand_details_blocks(html) == html
