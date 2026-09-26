"""Tests for video.py's title-card shrink-to-fit logic (_fit_fontsize). Added after a
real 76-character episode title was found to clip off both edges of the frame at a fixed
fontsize=60 -- see video.py's _fit_fontsize docstring for the full story."""

import video


def test_short_title_uses_the_full_max_fontsize():
    assert video._fit_fontsize("Ancient Rome", video.EPISODE_TITLE_MAX_FONTSIZE) == video.EPISODE_TITLE_MAX_FONTSIZE


def test_long_title_shrinks_below_max_fontsize():
    long_title = "Mastering Complex Numbers Algebra: A Journey Through the Hidden Dimensions"
    fitted = video._fit_fontsize(long_title, video.EPISODE_TITLE_MAX_FONTSIZE)
    assert fitted < video.EPISODE_TITLE_MAX_FONTSIZE


def test_long_title_actually_fits_within_the_frame_at_its_fitted_size():
    long_title = "Mastering Complex Numbers Algebra: A Journey Through the Hidden Dimensions"
    fitted = video._fit_fontsize(long_title, video.EPISODE_TITLE_MAX_FONTSIZE)
    width = video._measure_text_width(long_title, fitted)
    assert width <= video.FRAME_WIDTH * video.TITLE_MAX_WIDTH_RATIO


def test_never_shrinks_below_the_minimum_fontsize_even_for_extremely_long_text():
    absurdly_long_title = "A " * 200  # far longer than any real episode title
    fitted = video._fit_fontsize(absurdly_long_title, video.EPISODE_TITLE_MAX_FONTSIZE)
    assert fitted == video.MIN_TITLE_FONTSIZE


def test_fitted_fontsize_never_exceeds_the_requested_max():
    for title in ["A", "Ancient Rome", "A somewhat longer but still reasonable segment title"]:
        fitted = video._fit_fontsize(title, video.SEGMENT_TITLE_MAX_FONTSIZE)
        assert fitted <= video.SEGMENT_TITLE_MAX_FONTSIZE
