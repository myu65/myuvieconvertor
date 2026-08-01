from __future__ import annotations

import json
import re
from pathlib import Path

from .errors import ConfigurationError

IMAGE_PATTERN = re.compile(
    r"^/[A-Za-z0-9_$.-]+/[A-Za-z0-9_$.-]+/[A-Za-z0-9_$.-]+/[A-Za-z0-9_./:$-]+$"
)
STAGE_PATTERN = re.compile(r"^@[A-Za-z0-9_$.-]+(?:/[A-Za-z0-9_./$-]+)?$")
JOB_PATH_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_./-]*\.json$")


def _q(value: str) -> str:
    return json.dumps(value)


def render_job_spec(
    *,
    image: str,
    model_stage: str,
    job_stage: str,
    request_path: str,
    memory: str = "20Gi",
    cpu: str = "4",
) -> str:
    if not IMAGE_PATTERN.fullmatch(image):
        raise ConfigurationError(
            "image must be a full Snowflake image repository path beginning with /"
        )
    if not STAGE_PATTERN.fullmatch(model_stage) or not STAGE_PATTERN.fullmatch(job_stage):
        raise ConfigurationError(
            "stage names must begin with @ and contain only Snowflake identifier/path characters"
        )
    if not JOB_PATH_PATTERN.fullmatch(request_path) or ".." in Path(request_path).parts:
        raise ConfigurationError("request path must be a safe relative .json path")
    if not re.fullmatch(r"(?:[1-9][0-9]*|0\.[0-9]+)", cpu):
        raise ConfigurationError("cpu must be a positive numeric resource quantity")
    if not re.fullmatch(r"[1-9][0-9]*(?:M|Mi|G|Gi)", memory):
        raise ConfigurationError("memory must use an SPCS quantity such as 20Gi")
    request_mount_path = f"/mnt/jobs/{request_path}"
    return f"""spec:
  containers:
  - name: videoai
    image: {_q(image)}
    args:
    - run-job
    - --request
    - {_q(request_mount_path)}
    - --output-root
    - /mnt/jobs/results
    env:
      VIDEOAI_MODEL_ROOT: /mnt/models
      VIDEOAI_MODEL_CACHE: /scratch/models
      VIDEOAI_MATERIALIZE_MODELS: "1"
      VIDEOAI_WORK_ROOT: /scratch/work
      VIDEOAI_STAGE_MOUNTS: /mnt/jobs:/mnt/models
    resources:
      requests:
        cpu: {cpu}
        memory: {memory}
        nvidia.com/gpu: 1
      limits:
        memory: {memory}
        nvidia.com/gpu: 1
    volumeMounts:
    - name: models
      mountPath: /mnt/models
    - name: jobs
      mountPath: /mnt/jobs
    - name: scratch
      mountPath: /scratch
  volumes:
  - name: models
    source: stage
    stageConfig:
      name: {_q(model_stage)}
      metadataCache: 1h
  - name: jobs
    source: stage
    stageConfig:
      name: {_q(job_stage)}
  - name: scratch
    source: local
  logExporters:
    eventTableConfig:
      logLevel: INFO
  platformMonitor:
    metricConfig:
      groups:
      - system
      - storage
"""
