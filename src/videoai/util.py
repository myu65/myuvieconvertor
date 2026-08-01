from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .errors import BackendError, UnsafePathError


def json_dump(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def json_load(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_command(
    command: list[str],
    *,
    cwd: Path | None = None,
    timeout: int = 7200,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    started = time.monotonic()
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            env={**os.environ, **(env or {})},
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise BackendError(f"command timed out after {timeout}s: {command[0]}") from exc
    if result.returncode != 0:
        tail = "\n".join((result.stderr or result.stdout).splitlines()[-40:])
        raise BackendError(
            f"command failed ({result.returncode}) after {time.monotonic() - started:.1f}s: "
            f"{command[0]}\n{tail}"
        )
    return result


def require_artifact(path: Path, label: str, minimum_bytes: int = 1) -> Path:
    if not path.is_file() or path.stat().st_size < minimum_bytes:
        raise BackendError(f"{label} did not produce a valid artifact: {path}")
    return path


def stage_safe_copy(source: Path, destination: Path) -> None:
    """Copy to a local filesystem atomically, or stream directly to an SPCS stage mount.

    Current SPCS stage volumes do not support rename, so the local temp+replace pattern
    must not be used on a mounted stage.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    mounts = [
        Path(item) for item in os.getenv("VIDEOAI_STAGE_MOUNTS", "/mnt/jobs:/mnt/models").split(":")
    ]
    resolved = destination.resolve(strict=False)
    is_stage = any(resolved == mount or mount in resolved.parents for mount in mounts)
    if is_stage:
        with source.open("rb") as src, destination.open("wb") as dst:
            shutil.copyfileobj(src, dst, length=8 * 1024 * 1024)
            dst.flush()
            os.fsync(dst.fileno())
        return
    temporary = destination.with_name(f".{destination.name}.tmp-{os.getpid()}")
    shutil.copyfile(source, temporary)
    os.replace(temporary, destination)


def confined_path(root: Path, value: str, *, must_exist: bool = True) -> Path:
    if not value or Path(value).is_absolute():
        raise UnsafePathError(f"job path must be relative: {value!r}")
    path = (root / value).resolve(strict=False)
    resolved_root = root.resolve(strict=True)
    if path != resolved_root and resolved_root not in path.parents:
        raise UnsafePathError(f"job path escapes request directory: {value!r}")
    if must_exist and not path.exists():
        raise UnsafePathError(f"job input does not exist: {value!r}")
    return path


def copy_tree(source: Path, destination: Path, *, required: Iterable[str] = ()) -> None:
    if not source.is_dir():
        raise BackendError(f"model source is not a directory: {source}")
    destination.mkdir(parents=True, exist_ok=True)
    for relative in required:
        if not (source / relative).is_file():
            raise BackendError(f"model source is incomplete; missing {relative}")
    shutil.copytree(source, destination, dirs_exist_ok=True, copy_function=shutil.copyfile)
