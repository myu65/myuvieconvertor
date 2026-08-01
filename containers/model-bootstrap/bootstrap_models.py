from __future__ import annotations

import hashlib
import json
import os
import shutil
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


def main() -> None:
    lock_path = Path(os.getenv("MODEL_LOCK", "/config/models.lock.yaml"))
    output = Path(os.getenv("MODEL_OUTPUT", "/mnt/models/releases"))
    scratch = Path(os.getenv("MODEL_SCRATCH", "/scratch/downloads"))
    lock = yaml.safe_load(lock_path.read_text(encoding="utf-8"))
    api = HfApi(token=os.getenv("HF_TOKEN") or None)
    release = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = output / release
    manifest = {"schema_version": 1, "created_at": release, "models": []}

    for model in lock["models"]:
        info = api.model_info(model["repo_id"], revision=model["revision"], files_metadata=True)
        if info.sha != model["revision"]:
            raise RuntimeError(f"revision mismatch for {model['name']}: {info.sha}")
        lfs_sha256 = {
            sibling.rfilename: sibling.lfs.sha256
            for sibling in info.siblings
            if sibling.lfs is not None and sibling.lfs.sha256 is not None
        }
        target = scratch / model["name"]
        snapshot_download(
            repo_id=model["repo_id"],
            revision=model["revision"],
            local_dir=target,
            allow_patterns=model.get("allow_patterns"),
            token=os.getenv("HF_TOKEN") or None,
        )
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
        shutil.copytree(
            target,
            destination / model["name"],
            ignore=shutil.ignore_patterns(".cache"),
        )
        manifest["models"].append(
            {
                "name": model["name"],
                "repo_id": model["repo_id"],
                "revision": info.sha,
                "files": files,
                "verified_lfs_files": len(set(lfs_sha256) & {item["path"] for item in files}),
            }
        )
        shutil.rmtree(target)

    destination.mkdir(parents=True, exist_ok=True)
    (destination / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output / "CURRENT").write_text(release + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
