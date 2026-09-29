import os
import re

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
    # A ?v=<mtime> cache-busting suffix is expected (see _versioned_src) -- not an exact
    # src match -- so a browser can't keep showing a stale image after a regeneration.
    assert '<img src="/assets/plots/already-saved.png?v=' in result
    assert 'alt="Show it">' in result
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
    assert '<img src="/assets/plots/live-test.png?v=' in result
    assert 'alt="Show live">' in result
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


def test_image_url_changes_when_a_graph_is_regenerated(tmp_path):
    # The whole point of the ?v=<mtime> suffix (_versioned_src) is that regenerating a
    # graph under the same `name` produces a different <img src>, so a browser can't
    # keep showing bytes from before the edit -- reported live as "sometimes it's
    # cached and doesn't update," most noticeably right after Generate graph.
    text = '```matplotlib name="versioned"\nax = plt.gca()\nax.plot([0, 1], [0, 1])\n```'
    first = render_plots.process_live(text, tmp_path)
    second = render_plots.process_live(text, tmp_path)
    first_src = re.search(r'src="([^"]+)"', first).group(1)
    second_src = re.search(r'src="([^"]+)"', second).group(1)
    assert "?v=" in first_src
    assert first_src != second_src


def test_process_preview_url_reflects_the_saved_image_current_mtime(tmp_path):
    # process_preview never re-executes code, but its ?v= must still track whatever a
    # real save most recently wrote -- otherwise switching a block to view mode after a
    # save could still show a cached pre-save image.
    png_path = tmp_path / "saved.png"
    png_path.write_bytes(b"first version")
    text = '```matplotlib name="saved" title="Show it"\nraise RuntimeError("must not run")\n```'
    first = render_plots.process_preview(text, tmp_path)
    first_src = re.search(r'src="([^"]+)"', first).group(1)

    # Simulate a later real save rewriting the same file with a distinctly newer mtime.
    new_mtime = png_path.stat().st_mtime + 5
    os.utime(png_path, (new_mtime, new_mtime))

    second = render_plots.process_preview(text, tmp_path)
    second_src = re.search(r'src="([^"]+)"', second).group(1)
    assert first_src != second_src


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


def test_process_inline_true_shows_image_directly_not_behind_a_button(tmp_path):
    text = (
        '```matplotlib name="inline-test" title="Show inline" inline="true"\n'
        "ax = plt.gca()\n"
        "ax.plot([0, 1], [0, 1])\n"
        "```"
    )
    result = render_plots.process(text, tmp_path)
    assert "```matplotlib" not in result
    assert 'class="plot-widget plot-widget--inline"' in result
    assert 'class="plot-widget__inline-img"' in result
    assert 'data-plot="inline-test"' in result
    assert "plot-widget__toggle" not in result  # no button -- visible directly
    # Still clickable to open the exact same enlarge-in-a-modal popup a button gives.
    assert 'id="plot-modal-inline-test"' in result
    assert (tmp_path / "inline-test.png").exists()


def test_process_inline_false_behaves_like_the_default(tmp_path):
    text = '```matplotlib name="not-inline" inline="false"\nax = plt.gca()\nax.plot([0, 1], [0, 1])\n```'
    result = render_plots.process(text, tmp_path)
    assert "plot-widget--inline" not in result
    assert 'class="md-button plot-widget__toggle"' in result


def test_process_inline_true_without_a_title_still_parses(tmp_path):
    # inline is independently optional from title -- must work with title omitted
    # entirely, not just right after one.
    text = '```matplotlib name="no-title-inline" inline="true"\nax = plt.gca()\nax.plot([0, 1], [0, 1])\n```'
    result = render_plots.process(text, tmp_path)
    assert 'class="plot-widget__inline-img"' in result


def test_process_inline_true_puts_printed_output_next_to_the_image_not_in_the_modal(tmp_path):
    text = (
        '```matplotlib name="inline-printy" inline="true"\n'
        'print("checked: ok")\n'
        "ax = plt.gca()\n"
        "ax.plot([0, 1], [0, 1])\n"
        "```"
    )
    result = render_plots.process(text, tmp_path)
    # The output block appears once, before the modal starts -- not duplicated inside it.
    inline_img_index = result.index("plot-widget__inline-img")
    output_index = result.index("checked: ok")
    modal_index = result.index('id="plot-modal-inline-printy"')
    assert inline_img_index < output_index < modal_index


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
