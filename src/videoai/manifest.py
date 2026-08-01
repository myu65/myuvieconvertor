from __future__ import annotations

import platform
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from . import __version__
from .util import json_dump, sha256


@dataclass
class StepRecord:
    name: str
    status: str = "running"
    seconds: float | None = None
    detail: dict[str, Any] = field(default_factory=dict)
    _started: float = field(default_factory=time.monotonic, repr=False)

    def finish(self, **detail: Any) -> None:
        self.status = "ok"
        self.seconds = round(time.monotonic() - self._started, 3)
        self.detail.update(detail)

    def fail(self, message: str) -> None:
        self.status = "failed"
        self.seconds = round(time.monotonic() - self._started, 3)
        self.detail["error"] = message


@dataclass
class RunManifest:
    run_id: str
    mode: str
    profile: str
    target_language: str
    started_at_epoch: float = field(default_factory=time.time)
    steps: list[StepRecord] = field(default_factory=list)
    inputs: dict[str, Any] = field(default_factory=dict)
    outputs: dict[str, Any] = field(default_factory=dict)

    def step(self, name: str) -> StepRecord:
        item = StepRecord(name=name)
        self.steps.append(item)
        return item

    def add_input(self, name: str, path: Path) -> None:
        self.inputs[name] = {
            "path": str(path),
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
        }

    def add_output(self, name: str, path: Path) -> None:
        self.outputs[name] = {
            "path": str(path),
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
        }

    def write(self, path: Path) -> None:
        payload = asdict(self)
        payload["videoai_version"] = __version__
        payload["python"] = platform.python_version()
        payload["platform"] = platform.platform()
        json_dump(path, payload)
