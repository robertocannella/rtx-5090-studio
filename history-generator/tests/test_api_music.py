import pytest
from pydantic import ValidationError

import api


def test_job_request_music_defaults():
    req = api.JobRequest(topic="Test")
    assert req.music is False
    assert req.music_mood == "sleep-ambient"
    assert req.music_track_id is None


@pytest.mark.parametrize("value", [-41.0, -5.0, float("nan"), float("inf")])
def test_job_request_rejects_invalid_music_level(value):
    with pytest.raises(ValidationError):
        api.JobRequest(topic="Test", music=True, music_level_db=value)


@pytest.mark.parametrize("value", [-40.0, -25.0, -6.0])
def test_job_request_accepts_valid_music_level(value):
    req = api.JobRequest(topic="Test", music=True, music_level_db=value)
    assert req.music_level_db == value


@pytest.mark.parametrize("value", [-1.0, float("nan"), float("-inf")])
def test_job_request_rejects_invalid_fade(value):
    with pytest.raises(ValidationError):
        api.JobRequest(topic="Test", music=True, music_fade_in_seconds=value)


def test_job_request_accepts_explicit_track_id():
    req = api.JobRequest(topic="Test", music=True, music_track_id="abc123")
    assert req.music_track_id == "abc123"
