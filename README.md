# myuvieconvertor

Linux/NVIDIA GPUで、話者動画の翻訳吹替と静止画のトーキングヘッド生成を行うCLIです。UIはありません。初期の商用PoC向け構成を、ライセンスと再現性を優先して次に固定しています。

- ASR: Whisper large-v3 (`transformers`)
- 翻訳: Qwen3-4B-Instruct-2507（完全ローカル）またはOpenAI互換Chat Completions
- 音声: CosyVoice2-0.5B zero-shot voice cloning
- 口パク: MuseTalk 1.5
- 実行: ローカルDocker、またはSnowpark Container Servicesのjob service

モデルはDockerイメージに含めません。取得時の解決済みrevisionを `model-lock.json` に記録し、ローカルvolumeまたはSnowflake Stageから供給します。

## 対応範囲

安定運用プロファイルで音声合成を許可する言語は、日本語・英語・中国語・韓国語です。Qwenの翻訳能力はそれより広いものの、ピン留めしたCosyVoice2が正式対応する範囲をCLI側で制限しています。話者は1人、正面寄りの顔、遮蔽が少ない素材を想定します。

`dub` は元動画の長さを既定で維持します。翻訳後音声全体をピッチを保って時間調整するため、動画フレームがループしたり途中で切れたりしません。静止画向けの `talk` は生成音声の長さを使います。

## すぐ試す

Python 3.10以上とFFmpegが必要です。モデル取得だけならGPUは不要です。

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e .

# 4モデルを取得。合計サイズは大きいので十分な空き容量が必要です。
videoai models fetch --destination ./models
videoai models verify --root ./models
```

GPU実行環境は依存関係が衝突しやすいため、Dockerを推奨します。

```bash
docker build --platform linux/amd64 -t myuvieconvertor:dev .

docker run --rm --gpus all \
  -v "$PWD/models:/models:ro" \
  -v "$PWD/samples:/inputs:ro" \
  -v "$PWD/outputs:/outputs" \
  -e VIDEOAI_MODEL_ROOT=/models \
  myuvieconvertor:dev dub \
  --avatar /inputs/lecture.mp4 \
  --target-language en \
  --voice-reference /inputs/speaker.wav \
  --voice-transcript '参照音声で実際に話している文を正確に書く' \
  --translator qwen \
  --output /outputs/lecture-en.mp4
```

吹き出し画像などをしゃべらせる場合:

```bash
docker run --rm --gpus all \
  -v "$PWD/models:/models:ro" \
  -v "$PWD/samples:/inputs:ro" \
  -v "$PWD/outputs:/outputs" \
  -e VIDEOAI_MODEL_ROOT=/models \
  myuvieconvertor:dev talk \
  --avatar /inputs/comment.png \
  --text-file /inputs/comment-ja.txt \
  --target-language ja \
  --voice-reference /inputs/speaker.wav \
  --voice-transcript '参照音声の正確な文字起こし' \
  --output /outputs/comment.mp4
```

各実行は動画に加えて、監査用manifest、原文transcript、翻訳transcriptを出力します。外部翻訳APIを使う場合は `--translator openai` と `VIDEOAI_TRANSLATOR_BASE_URL`、`VIDEOAI_TRANSLATOR_MODEL`、`VIDEOAI_TRANSLATOR_API_KEY` を指定します。SPCSから外部APIへ出る場合はSnowflakeのExternal Access Integrationが別途必要です。

## GPUなしで動作確認

`mock` はモデルをロードせず、パス検証・manifest・Stage安全書込みを含むパイプライン全体を確認します。

```bash
videoai dub --profile mock \
  --avatar sample.mp4 --target-language en \
  --voice-reference reference.wav --voice-transcript 'reference words' \
  --output out.mp4
```

`videoai doctor --strict --model-root ./models` はFFmpeg、上流ソース、必要な重みを検査します。

## Snowflake

SPCSは常駐serviceではなく、処理終了時にコンテナが終了するjob serviceを使います。詳細は [docs/SNOWFLAKE.md](docs/SNOWFLAKE.md) を参照してください。job specは値を文字列連結せず、検証済みCLIで生成します。

```bash
videoai spcs render-job-spec \
  --image /VIDEOAI/APP/IMAGES/videoai:sha-abcdef0 \
  --model-stage @VIDEOAI.APP.MODELS/models \
  --job-stage @VIDEOAI.APP.JOBS \
  --request-path requests/job-001/request.json \
  --output job-001.yaml
```

## 品質上の注意

- 元話者の声を複製するため、本人・権利者の明示的な許可が必要です。
- WhisperX、pyannote、NLLBは初期構成に含めていません。モデルごとの追加条件や非商用条件が混入しやすいためです。
- `ttsfrd` は任意の閉じたバイナリ配布物なので使用せず、CosyVoiceのWeTextProcessing fallbackを使います。
- MuseTalk上流は失敗をcatchして終了コード0を返す場合があります。本CLIは出力ファイルの存在とサイズも検査します。
- MuseTalk上流の未引用shell pathを避けるため、ユーザー入力は制御された安全なファイル名へ複製してから渡します。
- 生成物にはAI生成・翻訳である旨を表示し、原文transcriptとmanifestを保存してください。

第三者コード・重みの条件と未解決事項は [docs/LICENSES.md](docs/LICENSES.md)、設計判断は [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) にあります。
