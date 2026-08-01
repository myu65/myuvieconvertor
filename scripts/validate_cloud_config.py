from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def load(relative: str):
    return yaml.safe_load((ROOT / relative).read_text(encoding="utf-8"))


def check(condition: object, message: str) -> None:
    if not condition:
        raise ValueError(message)


def main() -> None:
    required = [
        ".github/workflows/ci.yml",
        ".github/workflows/deploy-snowflake.yml",
        ".github/workflows/bootstrap-models.yml",
        ".github/workflows/gpu-smoke-test.yml",
        "config/models.lock.yaml",
        "config/model-licenses.yaml",
        "config.toml",
    ]
    for path in required:
        check((ROOT / path).is_file(), f"missing {path}")
    yaml_paths = sorted(ROOT.rglob("*.yaml")) + sorted(ROOT.rglob("*.yml"))
    for path in yaml_paths:
        load(path.relative_to(ROOT).as_posix())
    lock = load("config/models.lock.yaml")
    licenses = load("config/model-licenses.yaml")["models"]
    for model in lock["models"]:
        if model.get("repo_id"):
            check(re.fullmatch(r"[0-9a-f]{40}", model["revision"]), "revision must be a commit")
        else:
            check(model.get("external_files"), "direct source must declare external files")
            check(model["revision"] == "direct-sha256", "direct source must use SHA256 policy")
        check(model["name"] in licenses, f"missing license for {model['name']}")
        for digest in model["required_sha256"].values():
            check(re.fullmatch(r"[0-9a-f]{64}", digest), "invalid SHA256")
        check(model.get("required_files"), f"missing required file inventory for {model['name']}")
        check("required_globs" in model, f"missing required glob inventory for {model['name']}")
    runtime_names = {model.get("runtime_name", model["name"]) for model in lock["models"]}
    check("musetalk" in runtime_names, "MuseTalk release directory must match the runtime")
    gpu = (ROOT / "infra/spcs/gpu-smoke.yaml").read_text(encoding="utf-8")
    check("externalAccessIntegrations" not in gpu, "GPU spec must not have an EAI")
    offline_keys = ("HF_HUB_OFFLINE", "HF_DATASETS_OFFLINE", "TRANSFORMERS_OFFLINE", "PIP_NO_INDEX")
    for key in offline_keys:
        check(key in gpu, f"missing offline flag {key}")
    check("run-job" in gpu, "GPU smoke test must execute an end-to-end request")
    check("releases/__RELEASE_ID__" in gpu, "GPU smoke test must mount one immutable release")
    validate = (ROOT / "infra/spcs/model-validate.yaml").read_text(encoding="utf-8")
    check("externalAccessIntegrations" not in validate, "validation job must not have an EAI")
    for key in offline_keys:
        check(key in validate, f"missing validation offline flag {key}")
    workflow_paths = (ROOT / ".github/workflows").glob("*.yml")
    workflows = "\n".join(path.read_text(encoding="utf-8") for path in workflow_paths)
    check("SNOWFLAKE_PASSWORD" not in workflows, "password auth is forbidden")
    check("PRIVATE_KEY" not in workflows, "private-key auth is forbidden")
    check(
        "--eai-name MYUVIE_MODEL_DOWNLOAD_EAI" in workflows,
        "download job must receive the model EAI explicitly",
    )
    check(workflows.count("--eai-name") == 1, "only the download job may receive an EAI")


if __name__ == "__main__":
    main()
