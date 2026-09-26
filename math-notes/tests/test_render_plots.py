import pytest
import render_plots


def test_process_leaves_plain_markdown_unchanged():
    text = "# Title\n\nJust a normal paragraph, no graphs here."
    assert render_plots.process(text, "/tmp/does-not-matter") == text


def test_process_replaces_block_with_button_and_generates_image(tmp_path):
    text = (
        "Intro.\n\n"
        '```matplotlib name="test-plot" title="Show test"\n'
        "ax = plt.gca()\n"
        "ax.plot([0, 1, 2], [0, 1, 4])\n"
        "```\n\n"
        "Outro."
    )
    result = render_plots.process(text, tmp_path)

    assert "```matplotlib" not in result
    assert 'data-plot="test-plot"' in result
    assert "Show test" in result
    assert '/assets/plots/test-plot.png' in result
    assert (tmp_path / "test-plot.png").exists()
    assert (tmp_path / "test-plot.png").stat().st_size > 0


def test_process_raises_when_block_produces_no_plot(tmp_path):
    text = '```matplotlib name="empty"\nx = 1 + 1\n```'
    with pytest.raises(render_plots.PlotError):
        render_plots.process(text, tmp_path)


def test_process_raises_with_block_name_when_code_is_broken(tmp_path):
    text = '```matplotlib name="broken"\nthis is not valid python(((\n```'
    with pytest.raises(render_plots.PlotError, match="broken"):
        render_plots.process(text, tmp_path)


def test_process_handles_multiple_blocks_in_one_post(tmp_path):
    text = (
        '```matplotlib name="first"\nplt.gca().plot([0, 1])\n```\n\n'
        '```matplotlib name="second"\nplt.gca().plot([1, 0])\n```'
    )
    result = render_plots.process(text, tmp_path)
    assert 'data-plot="first"' in result
    assert 'data-plot="second"' in result
    assert (tmp_path / "first.png").exists()
    assert (tmp_path / "second.png").exists()
