import pytest
from pydantic import ValidationError

import api


@pytest.mark.parametrize("value", [-0.1, 2.1, float("nan"), float("inf"), float("-inf")])
def test_job_request_rejects_invalid_sentence_gap(value):
    with pytest.raises(ValidationError):
        api.JobRequest(topic="Test", sentence_gap_seconds=value)


@pytest.mark.parametrize("value", [0.0, 0.5, 1.0, 2.0])
def test_job_request_accepts_valid_sentence_gap(value):
    req = api.JobRequest(topic="Test", sentence_gap_seconds=value)
    assert req.sentence_gap_seconds == value


def test_job_request_defaults_sentence_gap_to_half_a_second():
    req = api.JobRequest(topic="Test")
    assert req.sentence_gap_seconds == 0.5
