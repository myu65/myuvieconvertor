# Snowpark Container Services deployment

SPCSアカウントがない環境でも仕様を静的検証できるよう、現行GAのservice specificationだけを使っています。実機では必ず短い10秒素材から確認してください。

## 1. Region and instance family

最初にアカウントで利用可能なfamilyを確認します。

```sql
SHOW COMPUTE POOL INSTANCE FAMILIES;
```

単一24 GB GPUを最低線とします。AWSは通常 `GPU_NV_S` (A10G 24 GB)ですが、AWS大阪regionでは公式表上利用不可です。Azureなら `GPU_NV_SM` (A10 24 GB)、GCPなら `GPU_GCP_NV_L4_1_24G`を候補にし、実際のSHOW結果を優先してください。

## 2. Objects and least privilege

以下は管理者が環境名を調整して実行する雛形です。

```sql
CREATE ROLE IF NOT EXISTS VIDEOAI_OWNER;
GRANT CREATE DATABASE ON ACCOUNT TO ROLE VIDEOAI_OWNER;
GRANT CREATE COMPUTE POOL ON ACCOUNT TO ROLE VIDEOAI_OWNER;

USE ROLE VIDEOAI_OWNER;
CREATE DATABASE IF NOT EXISTS VIDEOAI;
CREATE SCHEMA IF NOT EXISTS VIDEOAI.APP;
CREATE IMAGE REPOSITORY IF NOT EXISTS VIDEOAI.APP.IMAGES;
CREATE STAGE IF NOT EXISTS VIDEOAI.APP.MODELS ENCRYPTION = (TYPE = 'SNOWFLAKE_SSE');
CREATE STAGE IF NOT EXISTS VIDEOAI.APP.JOBS ENCRYPTION = (TYPE = 'SNOWFLAKE_SSE');
CREATE STAGE IF NOT EXISTS VIDEOAI.APP.SPECS ENCRYPTION = (TYPE = 'SNOWFLAKE_SSE');

CREATE COMPUTE POOL IF NOT EXISTS VIDEOAI_GPU_POOL
  MIN_NODES = 1
  MAX_NODES = 1
  INSTANCE_FAMILY = GPU_NV_S
  AUTO_RESUME = TRUE
  INITIALLY_SUSPENDED = TRUE
  AUTO_SUSPEND_SECS = 300;
```

実務ではdatabase作成とcompute pool作成を管理者、service/job実行を専用owner roleへ分離してください。job owner roleにはmodel stageのREAD、job stageのREAD/WRITE、image repositoryのREAD、compute poolのUSAGEが必要です。model stageにWRITEを与えないことでmountもread-onlyになります。

## 3. Build and push linux/amd64 image

```bash
docker build --platform linux/amd64 -t myuvieconvertor:sha-abcdef0 .
snow spcs image-registry login -c YOUR_CONNECTION

# SHOW IMAGE REPOSITORIESでrepository_urlを取得して置換
docker tag myuvieconvertor:sha-abcdef0 \
  ORG-ACCOUNT.registry.snowflakecomputing.com/videoai/app/images/videoai:sha-abcdef0
docker push ORG-ACCOUNT.registry.snowflakecomputing.com/videoai/app/images/videoai:sha-abcdef0
```

mutableな `latest` ではなくcommit SHA tagを使います。SPCSは `linux/amd64` imageのみ対応します。

## 4. Upload locked models

```bash
videoai models fetch --destination ./models
videoai models verify --root ./models
snow stage copy ./models @VIDEOAI.APP.MODELS/models \
  --recursive --no-auto-compress --overwrite -c YOUR_CONNECTION
```

stageはmodel serving cacheではありません。job specは `/mnt/models` からlocal volume `/scratch/models`へ一度コピーしてからモデルをロードします。これにより大量のrandom readをstage mountへ直接発行しません。

## 5. Submit a job

ローカルにjob folderを作ります。

```text
job-001/
  request.json
  lecture.mp4
  speaker.wav
```

`request.json`:

```json
{
  "mode": "dub",
  "avatar": "lecture.mp4",
  "output": "lecture-en.mp4",
  "target_language": "en",
  "voice_reference": "speaker.wav",
  "voice_transcript": "参照音声で実際に話している文を正確に記載する",
  "translator": "qwen",
  "duration_policy": "preserve"
}
```

```bash
snow stage copy ./job-001 @VIDEOAI.APP.JOBS/requests/job-001 \
  --recursive --no-auto-compress --overwrite -c YOUR_CONNECTION

videoai spcs render-job-spec \
  --image /VIDEOAI/APP/IMAGES/videoai:sha-abcdef0 \
  --model-stage @VIDEOAI.APP.MODELS/models \
  --job-stage @VIDEOAI.APP.JOBS \
  --request-path requests/job-001/request.json \
  --output job-001.yaml

snow stage copy ./job-001.yaml @VIDEOAI.APP.SPECS/jobs/ \
  --no-auto-compress --overwrite -c YOUR_CONNECTION
```

```sql
EXECUTE JOB SERVICE
  IN COMPUTE POOL VIDEOAI_GPU_POOL
  NAME = VIDEOAI_JOB_001
  FROM @VIDEOAI.APP.SPECS/jobs
  SPEC = 'job-001.yaml';
```

job serviceは既定で同期実行です。非同期化する場合は `ASYNC = TRUE` を公式構文の順序どおりに指定してください。結果は `@VIDEOAI.APP.JOBS/results/job-001/` に動画とJSONとして作られます。

## 6. Diagnose

```sql
SHOW SERVICE CONTAINERS IN SERVICE VIDEOAI_JOB_001;
SELECT SYSTEM$GET_SERVICE_LOGS('VIDEOAI_JOB_001', '0', 'videoai', 200);
SELECT * FROM TABLE(VIDEOAI_JOB_001!SPCS_GET_LOGS(
  START_TIME => DATEADD('hour', -1, CURRENT_TIMESTAMP())
));
```

確認点:

- `Container failed to start`: image path/READ privilege/linux-amd64を確認。
- `Unschedulable`: GPU requestとinstance family、pool capacityを確認。
- model missing: `snow stage list-files` と `model-lock.json`、recursive uploadを確認。
- Stage書込み失敗: job owner roleのWRITE privilegeを確認。
- 起動が遅い: stage sidecarとstorage metricsを確認。model materializationは毎job必要なので、小さいテスト素材でもcold startは短くならない。
- OOM: 1 GPUを明示要求しているか確認し、batch sizeを8から4へ下げる。モデルはprocessごとに終了するため、同時常駐はしない。

## 7. Cost controls

- job serviceを使い、常駐endpointは作らない。
- compute poolはSnowflake仕様上 `MIN_NODES` が1以上必須です。`MIN_NODES=1`, `MAX_NODES=1`, `INITIALLY_SUSPENDED=TRUE`, `AUTO_SUSPEND_SECS`を設定する。
- job serviceは自動cleanupされるが、compute pool状態と請求を別途監視する。
- 同じモデルを大量jobで繰返す場合だけ、block volume snapshotや常駐serviceの採算を再評価する。
