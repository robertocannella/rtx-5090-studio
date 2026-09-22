import pytest
from pydantic import ValidationError

import api


@pytest.mark.parametrize("value", ["nonsense", "current-events", "News"])
def test_job_request_rejects_invalid_domain(value):
    with pytest.raises(ValidationError):
        api.JobRequest(topic="Test", domain=value)


@pytest.mark.parametrize("value", ["history", "math", "discovery", "Math"])
def test_job_request_accepts_valid_domain(value):
    req = api.JobRequest(topic="Test", domain=value)
    assert req.domain in ("history", "math", "discovery")


def test_job_request_defaults_domain_to_history():
    req = api.JobRequest(topic="Test")
    assert req.domain == "history"
