import pytest
from pydantic import ValidationError

import api


@pytest.mark.parametrize("value", ["video", "MATHS", "animated"])
def test_job_request_rejects_invalid_visual_style(value):
    with pytest.raises(ValidationError):
        api.JobRequest(topic="Test", visual_style=value)


@pytest.mark.parametrize("value", ["static", "math", "images", "thumbnail", "Images", "STATIC"])
def test_job_request_accepts_valid_visual_style(value):
    req = api.JobRequest(topic="Test", visual_style=value)
    assert req.visual_style in ("static", "math", "images", "thumbnail")


def test_job_request_defaults_visual_style_to_static():
    req = api.JobRequest(topic="Test")
    assert req.visual_style == "static"
