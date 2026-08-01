from pathlib import Path

import pytest

from videoai.errors import BackendError
from videoai.models import selected_specs, verify_models


def test_unknown_model_rejected() -> None:
    with pytest.raises(BackendError):
        selected_specs(["nope"])


def test_verify_models_reports_missing(tmp_path: Path) -> None:
    missing = verify_models(tmp_path, ["cosyvoice2-0.5b"])
    assert any(item.endswith("cosyvoice2.yaml") for item in missing)
