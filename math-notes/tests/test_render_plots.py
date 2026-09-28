import pytest

import render_plots


def test_process_leaves_plain_markdown_unchanged(tmp_path):
    text = "# Title\n\nJust a normal paragraph, no graphs here."
    assert render_plots.process(text, tmp_path) == text


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
    assert 'class="md-button plot-widget__toggle"' in result
    assert "/assets/plots/test-plot.png" in result
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


def test_process_preview_shows_placeholder_when_never_saved(tmp_path):
    text = '```matplotlib name="never-saved"\nthis is not even valid python(((\n```'
    result = render_plots.process_preview(text, tmp_path)
    assert "```matplotlib" not in result
    assert "will render here after you save" in result
    assert not (tmp_path / "never-saved.png").exists()


def test_process_preview_never_executes_code():
    # A block whose code would raise if actually run -- process_preview must never
    # execute it (this is called on every keystroke-adjacent view toggle, not just save).
    text = '```matplotlib name="dangerous"\nraise RuntimeError("should never run")\n```'
    result = render_plots.process_preview(text, "/does/not/exist")  # path never touched
    assert "will render here after you save" in result


def test_process_preview_uses_existing_image_without_regenerating(tmp_path):
    (tmp_path / "already-saved.png").write_bytes(b"fake png bytes")
    text = '```matplotlib name="already-saved" title="Show it"\nraise RuntimeError("must not run")\n```'
    result = render_plots.process_preview(text, tmp_path)
    # Rendered directly and visibly (not the public site's click-to-reveal button+modal)
    # -- the editor's view mode is meant to show a block expanded by default.
    assert "plot-widget__preview" in result
    assert '<img src="/assets/plots/already-saved.png" alt="Show it">' in result
    assert "plot-widget__toggle" not in result
    assert (tmp_path / "already-saved.png").read_bytes() == b"fake png bytes"  # untouched


def test_process_live_executes_code_and_renders_visible_image(tmp_path):
    text = (
        '```matplotlib name="live-test" title="Show live"\n'
        "ax = plt.gca()\n"
        "ax.plot([0, 1], [0, 1])\n"
        "```"
    )
    result = render_plots.process_live(text, tmp_path)
    assert "```matplotlib" not in result
    assert "plot-widget__preview" in result
    assert '<img src="/assets/plots/live-test.png" alt="Show live">' in result
    assert "plot-widget__toggle" not in result  # visible directly, not behind a button
    assert (tmp_path / "live-test.png").exists()
    assert (tmp_path / "live-test.png").stat().st_size > 0


def test_process_live_raises_on_broken_code(tmp_path):
    # Unlike process_preview, process_live is an explicit "run this now" action -- it
    # must actually surface a broken block's error, not silently do nothing.
    text = '```matplotlib name="broken-live"\nthis is not valid python(((\n```'
    with pytest.raises(render_plots.PlotError, match="broken-live"):
        render_plots.process_live(text, tmp_path)


def test_process_live_overwrites_existing_image_in_its_own_directory(tmp_path):
    (tmp_path / "regen.png").write_bytes(b"stale bytes")
    text = '```matplotlib name="regen"\nax = plt.gca()\nax.plot([0, 1], [1, 0])\n```'
    render_plots.process_live(text, tmp_path)
    assert (tmp_path / "regen.png").read_bytes() != b"stale bytes"


def test_process_includes_printed_output_next_to_the_image(tmp_path):
    text = (
        '```matplotlib name="printy"\n'
        "a = 2.31\n"
        'print(f"acceleration = {a} m/s^2")\n'
        "ax = plt.gca()\n"
        "ax.plot([0, 1], [0, 1])\n"
        "```"
    )
    result = render_plots.process(text, tmp_path)
    assert 'class="plot-widget__output"' in result
    assert "acceleration = 2.31 m/s^2" in result
    assert (tmp_path / "printy.txt").read_text().strip() == "acceleration = 2.31 m/s^2"


def test_process_omits_output_block_when_nothing_was_printed(tmp_path):
    text = '```matplotlib name="quiet"\nax = plt.gca()\nax.plot([0, 1], [0, 1])\n```'
    result = render_plots.process(text, tmp_path)
    assert "plot-widget__output" not in result
    assert not (tmp_path / "quiet.txt").exists()


def test_process_escapes_printed_output(tmp_path):
    text = '```matplotlib name="unsafe"\nprint("<script>alert(1)</script>")\nplt.gca().plot([0, 1])\n```'
    result = render_plots.process(text, tmp_path)
    assert "<script>alert(1)</script>" not in result
    assert "&lt;script&gt;" in result


def test_process_removes_stale_output_file_once_code_stops_printing(tmp_path):
    (tmp_path / "was-printy.txt").write_text("old output")
    text = '```matplotlib name="was-printy"\nax = plt.gca()\nax.plot([0, 1], [0, 1])\n```'
    render_plots.process(text, tmp_path)
    assert not (tmp_path / "was-printy.txt").exists()


def test_process_preview_shows_previously_saved_output(tmp_path):
    # process_preview never re-executes code -- it must read back whatever a real save
    # already printed and persisted, not just the image.
    (tmp_path / "cached.png").write_bytes(b"fake png bytes")
    (tmp_path / "cached.txt").write_text("distance = 240.0 m")
    text = '```matplotlib name="cached" title="Show it"\nraise RuntimeError("must not run")\n```'
    result = render_plots.process_preview(text, tmp_path)
    assert "distance = 240.0 m" in result


def test_process_live_includes_printed_output(tmp_path):
    text = (
        '```matplotlib name="live-printy"\n'
        'print("checked: ok")\n'
        "ax = plt.gca()\n"
        "ax.plot([0, 1], [0, 1])\n"
        "```"
    )
    result = render_plots.process_live(text, tmp_path)
    assert 'class="plot-widget__output"' in result
    assert "checked: ok" in result
