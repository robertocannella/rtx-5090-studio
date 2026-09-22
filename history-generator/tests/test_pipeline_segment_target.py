import pytest

import pipeline


def test_estimate_segment_target_seconds_divides_budget_evenly_with_no_gap():
    target = pipeline.estimate_segment_target_seconds(300.0, 4, segment_gap_seconds=0.0)
    assert target == pytest.approx(75.0)


def test_estimate_segment_target_seconds_reserves_gap_time():
    # 4 segments -> 3 gaps of 5s = 15s reserved, leaving 285s split across 4 segments.
    target = pipeline.estimate_segment_target_seconds(300.0, 4, segment_gap_seconds=5.0)
    assert target == pytest.approx(285.0 / 4)


def test_estimate_segment_target_seconds_single_segment_has_no_gap_reserved():
    target = pipeline.estimate_segment_target_seconds(60.0, 1, segment_gap_seconds=5.0)
    assert target == pytest.approx(60.0)


def test_estimate_segment_target_seconds_floors_at_minimum():
    # An unreasonably tight budget must never yield a degenerate near-zero or negative target.
    target = pipeline.estimate_segment_target_seconds(10.0, 5, segment_gap_seconds=5.0)
    assert target >= pipeline.MIN_SEGMENT_TARGET_SECONDS


def test_estimate_segment_target_seconds_zero_count_returns_remaining():
    target = pipeline.estimate_segment_target_seconds(120.0, 0, segment_gap_seconds=1.5)
    assert target == pytest.approx(120.0)
