# Architecture and failure boundaries

## Pipeline

1. 入力を検査し、ランダムなrun workspaceへ安全な固定名でコピーする。
2. `dub` は16 kHz mono PCMへ変換し、Whisper large-v3で文字起こしする。
3. segment IDを保持したままQwenまたはOpenAI互換APIで翻訳する。
4. CosyVoice2を短命subprocessでロードし、参照音声から翻訳文を合成する。
5. `dub --duration-policy preserve` は音声を元動画尺へ合わせる。
6. 入力を25 fps、偶数解像度、H.264/yuv420pへ正規化する。静止画は音声尺の動画へ変換する。
7. MuseTalk 1.5を別subprocessで実行し、成果物の存在と最小サイズを検査する。
8. 動画、原文、翻訳文、ハッシュ入りmanifestを出力する。

重いモデルを同時に保持しません。ASR、翻訳、TTS、lip-syncは別プロセスなので、終了時にGPUメモリが解放されます。依存関係もDocker内の個別venvに分離し、CosyVoiceのTorch 2.3/CUDA 12.1系とMuseTalkのTorch 2.0/CUDA 11.8系を混ぜません。

## Threat model

ジョブJSON、入力ファイル名、翻訳API応答、上流プログラムの終了コードを信頼しません。

- job内の相対パスはrequest directoryからの脱出を拒否する。
- 出力名は単純な `.mp4` filenameだけを許可する。
- SPCS specのimage、stage、request pathはallowlist形式で検査し、YAML値をJSON quotingする。
- MuseTalkへ渡すmediaはrun workspace内の固定名へ正規化する。
- 翻訳はsegmentの件数、ID集合、重複、空文字を検査する。
- 外部processはtimeout、return code、成果物サイズを検査する。

## SPCS storage strategy

Snowflakeの現行stage volumeは大きな逐次I/O向けで、rename、append、random writeに向きません。したがって:

- `@MODELS` はREAD-only stage mountとし、job開始時にlocal volume `/scratch/models` へコピーする。
- 推論中のframes、pickle、一時WAVはlocal volumeだけに書く。
- 完成した動画・JSONだけを`/mnt/jobs/results/...`へ新規作成し、close/fsyncする。
- stage上でtemp fileをrenameするatomic-write patternは使わない。
- model stageだけ`metadataCache: 1h`を有効にし、実行中に更新するjob stageでは無効にする。

## Known quality boundary

全体尺は維持しますが、現在は翻訳segmentごとの発話開始時刻を再構築しません。長い沈黙やスライド切替に厳密な同期が必要な講話では、翻訳transcriptをレビューし、短いテストクリップで確認してから全編処理してください。複数話者のdiarizationも初版の対象外です。

