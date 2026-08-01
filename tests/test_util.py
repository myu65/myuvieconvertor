from pathlib import Path

import pytest

from videoai.errors import BackendError, UnsafePathError
from videoai.util import confined_path, require_artifact, stage_safe_copy


def test_confined_path_rejects_escape(tmp_path: Path) -> None:
    with pytest.raises(UnsafePathError):
        confined_path(tmp_path, "../secret.txt", must_exist=False)


def test_confined_path_accepts_child(tmp_path: Path) -> None:
    child = tmp_path / "media" / "a.mp4"
    child.parent.mkdir()
    child.write_bytes(b"x")
    assert confined_path(tmp_path, "media/a.mp4") == child


def test_stage_safe_copy_local_is_complete(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VIDEOAI_STAGE_MOUNTS", str(tmp_path / "not-stage"))
    source = tmp_path / "source"
    destination = tmp_path / "out" / "file"
    source.write_bytes(b"payload")
    stage_safe_copy(source, destination)
    assert destination.read_bytes() == b"payload"
    assert not list(destination.parent.glob("*.tmp-*"))


def test_require_artifact_rejects_tiny_file(tmp_path: Path) -> None:
    path = tmp_path / "empty"
    path.touch()
    with pytest.raises(BackendError):
        require_artifact(path, "test")
