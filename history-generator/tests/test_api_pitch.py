import pytest
from pydantic import ValidationError

import api


@pytest.mark.parametrize("value", [-4.1, 4.1, float("nan"), float("inf"), float("-inf")])
def test_job_request_rejects_invalid_pitch(value):
    with pytest.raises(ValidationError):
        api.JobRequest(topic="Test", pitch_semitones=value)


@pytest.mark.parametrize("value", [-4.0, 0.0, 2.0, 4.0])
def test_job_request_accepts_valid_pitch(value):
    req = api.JobRequest(topic="Test", pitch_semitones=value)
    assert req.pitch_semitones == value


def test_job_request_defaults_pitch_to_zero():
    req = api.JobRequest(topic="Test")
    assert req.pitch_semitones == 0.0
