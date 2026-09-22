import pytest
from pydantic import ValidationError

import api


@pytest.mark.parametrize("value", [-0.1, 10.1, float("nan"), float("inf"), float("-inf")])
def test_job_request_rejects_invalid_gap(value):
    with pytest.raises(ValidationError):
        api.JobRequest(topic="Test", segment_gap_seconds=value)


@pytest.mark.parametrize("value", [0.0, 1.5, 2.0, 10.0])
def test_job_request_accepts_valid_gap(value):
    req = api.JobRequest(topic="Test", segment_gap_seconds=value)
    assert req.segment_gap_seconds == value


def test_job_request_defaults_gap_to_one_point_five():
    req = api.JobRequest(topic="Test")
    assert req.segment_gap_seconds == 1.5
