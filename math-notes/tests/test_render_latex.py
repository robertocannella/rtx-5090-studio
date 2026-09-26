import render_latex


def test_process_leaves_plain_markdown_unchanged():
    text = "# Title\n\nJust a normal paragraph, no latex blocks here."
    assert render_latex.process(text) == text


def test_process_wraps_block_body_in_display_math_delimiters():
    text = '```latex\n\\int_0^\\infty e^{-x^2}\\,dx = \\frac{\\sqrt{\\pi}}{2}\n```'
    result = render_latex.process(text)
    assert result == "$$\n\\int_0^\\infty e^{-x^2}\\,dx = \\frac{\\sqrt{\\pi}}{2}\n$$"


def test_process_handles_multiple_blocks_in_one_post():
    text = '```latex\nx^2\n```\n\nSome text.\n\n```latex\ny^2\n```'
    result = render_latex.process(text)
    assert result.count("$$") == 4
    assert "x^2" in result and "y^2" in result


def test_process_preserves_multiline_body():
    text = '```latex\na = b\nc = d\n```'
    result = render_latex.process(text)
    assert result == "$$\na = b\nc = d\n$$"
