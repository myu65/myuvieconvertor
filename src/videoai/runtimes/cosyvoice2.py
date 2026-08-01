from __future__ import annotations

import argparse
import sys
from pathlib import Path


def run(
    text_file: Path,
    voice_reference: Path,
    voice_transcript_file: Path,
    model_path: Path,
    repo_path: Path,
    output: Path,
) -> None:
    if not repo_path.is_dir():
        raise FileNotFoundError(f"CosyVoice source directory not found: {repo_path}")
    if not model_path.is_dir():
        raise FileNotFoundError(f"CosyVoice2 model directory not found: {model_path}")
    sys.path.insert(0, str(repo_path))
    sys.path.insert(0, str(repo_path / "third_party" / "Matcha-TTS"))

    import torch
    import torchaudio
    from cosyvoice.cli.cosyvoice import CosyVoice2
    from cosyvoice.utils.file_utils import load_wav

    text = text_file.read_text(encoding="utf-8").strip()
    prompt_text = voice_transcript_file.read_text(encoding="utf-8").strip()
    if not text or not prompt_text:
        raise ValueError("speech text and voice-reference transcript must be non-empty")
    model = CosyVoice2(
        str(model_path),
        load_jit=False,
        load_trt=False,
        fp16=torch.cuda.is_available(),
        use_flow_cache=False,
    )
    prompt_audio = load_wav(str(voice_reference), 16000)
    pieces = [
        item["tts_speech"].detach().cpu()
        for item in model.inference_zero_shot(text, prompt_text, prompt_audio, stream=False)
    ]
    if not pieces:
        raise RuntimeError("CosyVoice2 returned no audio chunks")
    speech = torch.cat(pieces, dim=1)
    output.parent.mkdir(parents=True, exist_ok=True)
    torchaudio.save(str(output), speech, model.sample_rate)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--text-file", type=Path, required=True)
    parser.add_argument("--voice-reference", type=Path, required=True)
    parser.add_argument("--voice-transcript-file", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(
        args.text_file,
        args.voice_reference,
        args.voice_transcript_file,
        args.model,
        args.repo,
        args.output,
    )


if __name__ == "__main__":
    main()
