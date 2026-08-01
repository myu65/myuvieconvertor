import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


def _module():
    path = Path("containers/model-bootstrap/bootstrap_models.py")
    spec = importlib.util.spec_from_file_location("bootstrap_models", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _release(tmp_path: Path):
    payload = b"verified model payload"
    digest = hashlib.sha256(payload).hexdigest()
    destination = tmp_path / "release"
    model_file = destination / "musetalk" / "aux" / "weight.bin"
    model_file.parent.mkdir(parents=True)
    model_file.write_bytes(payload)
    lock = {
        "models": [
            {
                "name": "component",
                "runtime_name": "musetalk",
                "destination_prefix": "aux",
                "revision": "a" * 40,
                "required_files": ["weight.bin"],
                "required_globs": [],
            }
        ]
    }
    manifest = {
        "release_id": "release-1",
        "models": [
            {
                "name": "component",
                "runtime_name": "musetalk",
                "revision": "a" * 40,
                "files": [{"path": "aux/weight.bin", "sha256": digest, "bytes": len(payload)}],
            }
        ],
    }
    (destination / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return lock, destination, model_file


def test_validate_release_accepts_consolidated_runtime_directory(tmp_path: Path) -> None:
    module = _module()
    lock, destination, _ = _release(tmp_path)
    result = module.validate_release(lock, destination, "release-1")
    assert result["release_id"] == "release-1"


def test_validate_release_rejects_corrupted_stage_file(tmp_path: Path) -> None:
    module = _module()
    lock, destination, model_file = _release(tmp_path)
    model_file.write_bytes(b"x" * model_file.stat().st_size)
    with pytest.raises(RuntimeError, match="SHA256 mismatch"):
        module.validate_release(lock, destination, "release-1")


def test_release_id_rejects_unsafe_value(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _module()
    monkeypatch.setenv("MODEL_RELEASE_ID", "../escape")
    with pytest.raises(RuntimeError, match="invalid MODEL_RELEASE_ID"):
        module._release_id()
