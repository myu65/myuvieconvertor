from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import re
import shutil
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import yaml
from huggingface_hub import HfApi, snapshot_download


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _release_id() -> str:
    value = os.environ.get("MODEL_RELEASE_ID", "").strip()
    if not value:
        value = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", value):
        raise RuntimeError(f"invalid MODEL_RELEASE_ID: {value!r}")
    return value


def _runtime_name(model: dict[str, object]) -> str:
    return str(model.get("runtime_name") or model["name"])


def _destination_path(model: dict[str, object], relative: str) -> str:
    prefix = str(model.get("destination_prefix") or "").strip("/")
    return f"{prefix}/{relative}" if prefix else relative


def _required_paths(model: dict[str, object], files: list[str], *, destination: bool) -> None:
    required = [str(path) for path in model.get("required_files", [])]
    patterns = [str(path) for path in model.get("required_globs", [])]
    if destination:
        required = [_destination_path(model, path) for path in required]
        patterns = [_destination_path(model, path) for path in patterns]
    missing = set(required) - set(files)
    for pattern in patterns:
        if not any(fnmatch.fnmatch(path, pattern) for path in files):
            missing.add(pattern)
    if missing:
        raise RuntimeError(f"required files missing for {model['name']}: {sorted(missing)}")


def validate_release(lock: dict[str, object], destination: Path, release: str) -> dict[str, object]:
    manifest_path = destination / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("release_id") != release:
        raise RuntimeError("manifest release ID does not match requested release")
    expected = {str(model["name"]): model for model in lock["models"]}
    actual = {str(model["name"]): model for model in manifest.get("models", [])}
    if set(actual) != set(expected):
        raise RuntimeError(
            f"manifest model set mismatch: expected {sorted(expected)}, got {sorted(actual)}"
        )
    for name, locked in expected.items():
        item = actual[name]
        if item.get("revision") != locked["revision"]:
            raise RuntimeError(f"manifest revision mismatch for {name}")
        runtime_name = _runtime_name(locked)
        if item.get("runtime_name") != runtime_name:
            raise RuntimeError(f"manifest runtime name mismatch for {name}")
        model_root = destination / runtime_name
        files = [str(file["path"]) for file in item.get("files", [])]
        _required_paths(locked, files, destination=True)
        for file in item.get("files", []):
            path = model_root / str(file["path"])
            if not path.is_file() or path.stat().st_size != int(file["bytes"]):
                raise RuntimeError(
                    f"manifest file missing or wrong size: {runtime_name}/{file['path']}"
                )
            if sha256(path) != file["sha256"]:
                raise RuntimeError(f"manifest SHA256 mismatch: {runtime_name}/{file['path']}")
    return manifest


def _download_external_files(model: dict[str, object], target: Path) -> None:
    for artifact in model.get("external_files", []):
        path = target / str(artifact["path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        url = str(artifact["url"])
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != "https" or parsed.hostname not in {
            "drive.usercontent.google.com",
            "download.pytorch.org",
        }:
            raise RuntimeError(f"external artifact URL is not allowlisted: {url}")
        request = urllib.request.Request(  # noqa: S310 - HTTPS host allowlist above
            url, headers={"User-Agent": "myuvie-model-bootstrap/1"}
        )
        with urllib.request.urlopen(  # noqa: S310 - validated HTTPS request
            request, timeout=300
        ) as response, path.open("wb") as stream:
            shutil.copyfileobj(response, stream, length=8 * 1024 * 1024)


def bootstrap(lock: dict[str, object], output: Path, scratch: Path, release: str) -> None:
    api = HfApi(token=os.getenv("HF_TOKEN") or None)
    destination = output / release
    if destination.exists():
        raise RuntimeError(f"immutable model release already exists: {release}")
    manifest = {
        "schema_version": 1,
        "release_id": release,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "models": [],
    }

    for model in lock["models"]:
        target = scratch / model["name"]
        target.mkdir(parents=True, exist_ok=False)
        if model.get("repo_id"):
            info = api.model_info(
                model["repo_id"], revision=model["revision"], files_metadata=True
            )
            if info.sha != model["revision"]:
                raise RuntimeError(f"revision mismatch for {model['name']}: {info.sha}")
            lfs_sha256 = {
                sibling.rfilename: sibling.lfs.sha256
                for sibling in info.siblings
                if sibling.lfs is not None and sibling.lfs.sha256 is not None
            }
            snapshot_download(
                repo_id=model["repo_id"],
                revision=model["revision"],
                local_dir=target,
                allow_patterns=model.get("allow_patterns"),
                token=os.getenv("HF_TOKEN") or None,
            )
            resolved_revision = info.sha
        else:
            lfs_sha256 = {}
            _download_external_files(model, target)
            resolved_revision = model["revision"]
        files = []
        expected = model.get("required_sha256", {})
        for path in sorted(target.rglob("*")):
            if not path.is_file() or ".cache" in path.parts:
                continue
            relative = path.relative_to(target).as_posix()
            actual = sha256(path)
            if relative in lfs_sha256 and actual != lfs_sha256[relative]:
                raise RuntimeError(f"Hugging Face LFS SHA256 mismatch: {model['name']}/{relative}")
            if relative in expected and actual != expected[relative]:
                raise RuntimeError(f"SHA256 mismatch: {model['name']}/{relative}")
            files.append({"path": relative, "sha256": actual, "bytes": path.stat().st_size})
        missing = set(expected) - {item["path"] for item in files}
        if missing:
            raise RuntimeError(f"locked files missing for {model['name']}: {sorted(missing)}")
        _required_paths(model, [item["path"] for item in files], destination=False)
        runtime_name = _runtime_name(model)
        destination_prefix = str(model.get("destination_prefix") or "")
        manifest_files = [
            {**item, "path": _destination_path(model, item["path"])} for item in files
        ]
        shutil.copytree(
            target,
            destination / runtime_name / destination_prefix,
            ignore=shutil.ignore_patterns(".cache"),
            dirs_exist_ok=True,
        )
        manifest["models"].append(
            {
                "name": model["name"],
                "runtime_name": runtime_name,
                "repo_id": model.get("repo_id"),
                "revision": resolved_revision,
                "files": manifest_files,
                "verified_lfs_files": len(set(lfs_sha256) & {item["path"] for item in files}),
            }
        )
        shutil.rmtree(target)

    destination.mkdir(parents=True, exist_ok=True)
    (destination / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    validate_release(lock, destination, release)
    (output / "CURRENT").write_text(release + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "operation", choices=("bootstrap", "validate"), nargs="?", default="bootstrap"
    )
    args = parser.parse_args()
    lock_path = Path(os.getenv("MODEL_LOCK", "/config/models.lock.yaml"))
    output = Path(os.getenv("MODEL_OUTPUT", "/mnt/models/releases"))
    scratch = Path(os.getenv("MODEL_SCRATCH", "/scratch/downloads"))
    lock = yaml.safe_load(lock_path.read_text(encoding="utf-8"))
    release = _release_id()
    destination = output / release
    if args.operation == "bootstrap":
        bootstrap(lock, output, scratch, release)
    manifest = validate_release(lock, destination, release)
    summary = {
        "release_id": release,
        "models": [
            {
                "name": item["name"],
                "runtime_name": item["runtime_name"],
                "revision": item["revision"],
                "files": len(item["files"]),
                "bytes": sum(file["bytes"] for file in item["files"]),
            }
            for item in manifest["models"]
        ],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
