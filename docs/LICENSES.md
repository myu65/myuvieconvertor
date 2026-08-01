# Third-party license inventory

これは法的助言ではありません。2026-08-01時点で、上流repository/model cardに明記された条件を実装で固定した台帳です。配布前に組織の法務・知財手順で再確認してください。

| Component | Pinned artifact | Declared license | Use in this project | Status |
|---|---|---|---|---|
| [OpenAI Whisper large-v3](https://huggingface.co/openai/whisper-large-v3) | resolved revision in lock | MIT | ASR weights through Transformers | Allowed with notice |
| Hugging Face Transformers | Docker-pinned version | Apache-2.0 | ASR/Qwen runtime | Allowed with notice |
| [Qwen3-4B-Instruct-2507](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507) | resolved revision in lock | Apache-2.0 | Local translation | Allowed with notice |
| [CosyVoice source](https://github.com/FunAudioLLM/CosyVoice) | `3bf48f125a8c25d3f9c386cdb3abf2b614391817` | Apache-2.0 | TTS runtime | Allowed with Apache notice |
| [CosyVoice2-0.5B weights](https://huggingface.co/FunAudioLLM/CosyVoice2-0.5B) | `7532de4ab5a24a119fbc93fdc27449a329649a4a` | Apache-2.0 in model card | Zero-shot voice cloning | Allowed with notice; consent still required |
| [MuseTalk source](https://github.com/TMElyralab/MuseTalk) | `0a89dec45a0192b824e3cf4daf96c239440c5ed8` | MIT | Lip-sync | Allowed with notice |
| MuseTalk 1.5 weights | resolved revision in lock | MIT stated by project LICENSE | Lip-sync UNet | Allowed with notice |
| MuseTalk SD VAE | `stabilityai/sd-vae-ft-mse` snapshot bundled by upstream download recipe | MIT stated by MuseTalk LICENSE | VAE | Allowed with notice |
| MuseTalk Whisper tiny | `openai/whisper-tiny` | MIT | Audio feature encoder | Allowed with notice |
| DWPose | upstream model snapshot | Apache-2.0 stated by MuseTalk LICENSE | Landmark processing | Allowed with notice |
| face-parsing.PyTorch code | upstream | MIT | Face mask | Allowed with notice |
| face parser `79999_iter.pth` | Google Drive ID used by MuseTalk official script | Weight-specific license not separately stated | Face parsing | **Legal confirmation recommended** |
| ResNet-18 weights | PyTorch official URL | BSD-style PyTorch terms | Face parsing backbone | Keep attribution |
| FFmpeg Ubuntu package | Distribution build has GPL features enabled | GPL/LGPL components | External process for media conversion | Preserve package notices/source-offer obligations for redistributed image |
| NVIDIA CUDA base image | `nvidia/cuda:12.1.1-cudnn8-runtime-ubuntu22.04` | NVIDIA container/CUDA terms | GPU runtime | Review enterprise redistribution terms |

## Deliberately excluded

- WhisperX: codeはBSD系でも、自動取得されるalignment modelが言語により異なり、非商用条件を含む場合があるため既定経路から除外。
- pyannote diarization: gated modelの同意、token、モデル条件が必要なため除外。
- NLLB-200: CC-BY-NC-4.0のため商用PoC既定から除外。
- XTTS v2: Coqui Public Model Licenseの用途制約があるため除外。
- CosyVoice `ttsfrd`: 任意配布のbinary wheel/resourceを避け、WeTextProcessingを使用。
- Edge TTS/クラウド音声: OSSローカル構成ではないため既定から除外。

## Distribution checklist

1. Docker imageのSBOMを作り、実際に解決されたPython/OS package licenseを確認する。
2. `model-lock.json` と本台帳をリリース成果物に含める。
3. Apache/MIT/BSD noticesを同梱する。
4. face parser weightの出所・重みライセンスを知財部門で確認する。
5. 話者のvoice/likeness consent、原動画、翻訳、公開地域の権利をjob単位で記録する。
