# Snowflake Cloud deployment

This repository deploys from GitHub-hosted runners; WSL and a developer workstation are not
part of the production path. The `snowflake-dev` GitHub Environment is restricted to `main`, so
all Snowflake workflows are manual and must be invoked from `main` after review and merge.

## Fixed resources

| Resource | Value |
| --- | --- |
| Account | `HTXCFQM-QG85847` |
| WIF user / role | `MYUVIE_GITHUB` / `MYUVIE_DEV` |
| Database / schema | `MYUVIE_DB.APP` |
| Image repository | `MYUVIE_DB.APP.IMAGES` |
| Stages | `MODELS`, `MEDIA`, `SPECS` |
| GPU pool | `MYUVIE_GPU_A10` (`GPU_NV_S`, one A10G 24 GB) |
| CPU model pool | `MYUVIE_CPU_MODELS` |

Both pools use `AUTO_RESUME=FALSE`. Only their dedicated manual workflows issue `RESUME`, and an
`if: always()` cleanup step issues `SUSPEND` and displays the final state.

## Promotion sequence

1. Run CI on the pull request: Ruff, pytest, YAML/SQL policy checks, and both linux/amd64 builds.
2. Merge the reviewed Draft PR to `main`.
3. Dispatch `Snowflake OIDC and deploy` with `oidc-check`.
4. Dispatch it with `push-image`.
5. Dispatch `Bootstrap models on CPU` first with `push-bootstrap-image`, then `run-cpu-job`.
6. The workflow runs a second validation job without an EAI and publishes the complete SHA256
   manifest under `@MODELS/releases/<release-id>/manifest.json` as a workflow artifact and summary.
7. Stop for a human cost/safety decision before dispatching `GPU smoke test`.

The GPU workflow additionally requires the literal confirmation `RESUME-MYUVIE-GPU-A10`.

## Authentication

`config.toml` contains identifiers only. `snowflakedb/snowflake-actions@v3` requests a short-lived
GitHub OIDC token and exports it as `SNOWFLAKE_CONNECTIONS_MYUVIE_TOKEN`. No password, private key,
or long-lived Snowflake credential is stored in GitHub Secrets.

`infra/snowflake/02_wif.sql` records the hardened Environment subject. Administrator-only creation
of the network rule/EAI is isolated in `01_external_access.sql`; it must not be added to an
inference job.

## Model supply chain

`config/models.lock.yaml` pins every Hugging Face repository to a 40-character commit. Known
high-value artifacts have committed SHA256 values. The CPU-only bootstrap container downloads each
snapshot to local scratch, rejects a revision or locked hash mismatch, calculates SHA256 for every
file, then copies the verified release and manifest to the `MODELS` stage. Official MuseTalk
auxiliary sources are separate pinned components and are consolidated into the runtime `musetalk`
directory. Only the download job receives `MYUVIE_MODEL_DOWNLOAD_EAI`; a second job mounts the
release with no EAI, forces offline mode, and verifies every manifest digest and required file.

The inference image and generated GPU spec force `HF_HUB_OFFLINE`, `HF_DATASETS_OFFLINE`,
`TRANSFORMERS_OFFLINE`, and `PIP_NO_INDEX`. The GPU job has no External Access Integration.

## GPU memory policy

Whisper large-v3, Qwen, CosyVoice2, and MuseTalk run in separate child processes. The orchestrator waits
for each child to exit before starting the next, so model memory is released between phases and the
models never remain resident together on the 24 GB GPU. The GPU workflow renders an end-to-end
`run-job` specification from a verified release ID and a short, non-sensitive request in `@MEDIA`.

## License gate

The technical bootstrap does not clear the legal gate. The MuseTalk GitHub README permits
commercial use, while its Hugging Face metadata declares CreativeML-OpenRAIL-M. The LatentSync
SyncNet component is OpenRAIL++, and the official Google Drive face-parser checkpoint has no
separately stated weight license. Record legal approval (or replace those artifacts with approved
alternatives) before acknowledging GPU cost and dispatching the smoke test.

## Bootstrap SQL

Run `infra/snowflake/00_objects.sql` with a role that owns the existing objects. Run
`01_external_access.sql` and `02_wif.sql` only with the administrator roles named in those files.
Do not put administrator execution into GitHub Actions.

The official references used for these files are the Snowflake CLI GitHub Action, workload identity
federation, image repository, compute pool, service specification, and `EXECUTE JOB SERVICE`
documentation.
