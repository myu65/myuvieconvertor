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
        check(re.fullmatch(r"[0-9a-f]{40}", model["revision"]), "revision must be a commit")
        check(model["name"] in licenses, f"missing license for {model['name']}")
        for digest in model["required_sha256"].values():
            check(re.fullmatch(r"[0-9a-f]{64}", digest), "invalid SHA256")
    gpu = (ROOT / "infra/spcs/gpu-smoke.yaml").read_text(encoding="utf-8")
    check("externalAccessIntegrations" not in gpu, "GPU spec must not have an EAI")
    offline_keys = ("HF_HUB_OFFLINE", "HF_DATASETS_OFFLINE", "TRANSFORMERS_OFFLINE", "PIP_NO_INDEX")
    for key in offline_keys:
        check(key in gpu, f"missing offline flag {key}")
    workflow_paths = (ROOT / ".github/workflows").glob("*.yml")
    workflows = "\n".join(path.read_text(encoding="utf-8") for path in workflow_paths)
    check("SNOWFLAKE_PASSWORD" not in workflows, "password auth is forbidden")
    check("PRIVATE_KEY" not in workflows, "private-key auth is forbidden")


if __name__ == "__main__":
    main()
