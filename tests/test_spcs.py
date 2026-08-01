import pytest
import yaml

from videoai.errors import ConfigurationError
from videoai.spcs import render_job_spec


def test_rendered_spcs_spec_is_valid_current_stage_volume_shape() -> None:
    rendered = render_job_spec(
        image="/DB/APP/IMAGES/videoai:sha-abc",
        model_stage="@DB.APP.MODELS/models",
        job_stage="@DB.APP.JOBS",
        request_path="requests/job-1/request.json",
    )
    spec = yaml.safe_load(rendered)["spec"]
    assert spec["containers"][0]["resources"]["requests"]["nvidia.com/gpu"] == 1
    assert spec["volumes"][0]["source"] == "stage"
    assert spec["volumes"][0]["stageConfig"]["name"].startswith("@")
    assert spec["volumes"][2]["source"] == "local"
    assert spec["containers"][0]["args"][2] == "/mnt/jobs/requests/job-1/request.json"


@pytest.mark.parametrize(
    "field,value",
    [
        ("image", "evil\nvalue"),
        ("model_stage", "DB.APP.MODELS"),
        ("request_path", "../request.json"),
    ],
)
def test_rendered_spcs_spec_rejects_injection(field: str, value: str) -> None:
    kwargs = {
        "image": "/DB/APP/IMAGES/videoai:latest",
        "model_stage": "@DB.APP.MODELS",
        "job_stage": "@DB.APP.JOBS",
        "request_path": "requests/job/request.json",
    }
    kwargs[field] = value
    with pytest.raises(ConfigurationError):
        render_job_spec(**kwargs)
