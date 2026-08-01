from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from .errors import BackendError
from .util import copy_tree, json_dump


@dataclass(frozen=True)
class ModelSpec:
    name: str
    repo_id: str
    revision: str | None
    allow_patterns: tuple[str, ...] | None = None


MODEL_SPECS = (
    ModelSpec("whisper-large-v3", "openai/whisper-large-v3", None),
    ModelSpec(
        "cosyvoice2-0.5b", "FunAudioLLM/CosyVoice2-0.5B", "7532de4ab5a24a119fbc93fdc27449a329649a4a"
    ),
    ModelSpec(
        "musetalk",
        "TMElyralab/MuseTalk",
        None,
        (
            "musetalkV15/*",
            "syncnet/*",
            "dwpose/*",
            "sd-vae/*",
            "whisper/*",
        ),
    ),
    ModelSpec("qwen3-4b-instruct-2507", "Qwen/Qwen3-4B-Instruct-2507", None),
)


REQUIRED_FILES = {
    "whisper-large-v3": ("config.json", "model.safetensors", "preprocessor_config.json"),
    "cosyvoice2-0.5b": (
        "cosyvoice2.yaml",
        "llm.pt",
        "flow.pt",
        "hift.pt",
        "speech_tokenizer_v2.onnx",
    ),
    "musetalk": (
        "musetalkV15/musetalk.json",
        "musetalkV15/unet.pth",
        "sd-vae/config.json",
        "sd-vae/diffusion_pytorch_model.bin",
        "whisper/config.json",
        "whisper/pytorch_model.bin",
        "dwpose/dw-ll_ucoco_384.pth",
        "syncnet/latentsync_syncnet.pt",
        "face-parse-bisent/79999_iter.pth",
        "face-parse-bisent/resnet18-5c106cde.pth",
    ),
    "qwen3-4b-instruct-2507": ("config.json", "tokenizer.json"),
}
REQUIRED_GLOBS = {
    "whisper-large-v3": ("*.safetensors",),
    "qwen3-4b-instruct-2507": ("*.safetensors",),
}


def selected_specs(names: Iterable[str]) -> list[ModelSpec]:
    wanted = set(names)
    known = {item.name for item in MODEL_SPECS}
    unknown = wanted - known
    if unknown:
        raise BackendError(f"unknown model name(s): {', '.join(sorted(unknown))}")
    return [item for item in MODEL_SPECS if item.name in wanted]


def fetch_models(destination: Path, names: Iterable[str]) -> Path:
    from huggingface_hub import HfApi, snapshot_download

    destination.mkdir(parents=True, exist_ok=True)
    api = HfApi(token=os.getenv("HF_TOKEN") or None)
    locked: list[dict[str, object]] = []
    for spec in selected_specs(names):
        info = api.model_info(spec.repo_id, revision=spec.revision)
        resolved = str(info.sha)
        local = destination / spec.name
        snapshot_download(
            repo_id=spec.repo_id,
            revision=resolved,
            local_dir=local,
            allow_patterns=list(spec.allow_patterns) if spec.allow_patterns else None,
            token=os.getenv("HF_TOKEN") or None,
        )
        locked.append({"name": spec.name, "repo_id": spec.repo_id, "revision": resolved})
    if "musetalk" in {item.name for item in selected_specs(names)}:
        _fetch_musetalk_face_parser(destination / "musetalk" / "face-parse-bisent")
    lock_path = destination / "model-lock.json"
    json_dump(lock_path, {"schema_version": 1, "models": locked})
    return lock_path


def _fetch_musetalk_face_parser(destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    face = destination / "79999_iter.pth"
    resnet = destination / "resnet18-5c106cde.pth"
    if not face.exists():
        command = [
            sys.executable,
            "-m",
            "gdown",
            "--id",
            "154JgKpzCPW82qINcVieuPH3fZ2e0P812",
            "-O",
            str(face),
        ]
        result = subprocess.run(command, check=False)
        if result.returncode != 0:
            raise BackendError("failed to download MuseTalk face parser weight with gdown")
    if not resnet.exists():
        import urllib.request

        urllib.request.urlretrieve(
            "https://download.pytorch.org/models/resnet18-5c106cde.pth", resnet
        )


def verify_models(root: Path, names: Iterable[str]) -> list[str]:
    missing: list[str] = []
    for spec in selected_specs(names):
        for relative in REQUIRED_FILES[spec.name]:
            path = root / spec.name / relative
            if not path.is_file() or path.stat().st_size == 0:
                missing.append(str(path))
        for pattern in REQUIRED_GLOBS.get(spec.name, ()):
            if not any(
                path.is_file() and path.stat().st_size > 0
                for path in (root / spec.name).glob(pattern)
            ):
                missing.append(str(root / spec.name / pattern))
    return missing


def materialize_models(source: Path, destination: Path, names: Iterable[str]) -> None:
    selected = selected_specs(names)
    for spec in selected:
        copy_tree(
            source / spec.name,
            destination / spec.name,
            required=REQUIRED_FILES[spec.name],
        )
    lock = source / "model-lock.json"
    if lock.is_file():
        shutil.copyfile(lock, destination / "model-lock.json")
    missing = verify_models(destination, [item.name for item in selected])
    if missing:
        raise BackendError(f"materialized model cache is incomplete: {', '.join(missing)}")


def model_lock(root: Path) -> dict[str, object] | None:
    path = root / "model-lock.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
