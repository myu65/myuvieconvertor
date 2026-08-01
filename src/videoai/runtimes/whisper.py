from __future__ import annotations

import argparse
import json
from pathlib import Path


def run(input_path: Path, model_path: Path, output: Path) -> None:
    import torch
    from transformers import AutoModelForSpeechSeq2Seq, AutoProcessor, pipeline

    if not model_path.is_dir():
        raise FileNotFoundError(f"Whisper model directory not found: {model_path}")
    device = "cuda:0" if torch.cuda.is_available() else "cpu"
    dtype = torch.float16 if torch.cuda.is_available() else torch.float32
    model = AutoModelForSpeechSeq2Seq.from_pretrained(
        model_path,
        torch_dtype=dtype,
        low_cpu_mem_usage=True,
        use_safetensors=True,
    ).to(device)
    processor = AutoProcessor.from_pretrained(model_path)
    transcriber = pipeline(
        "automatic-speech-recognition",
        model=model,
        tokenizer=processor.tokenizer,
        feature_extractor=processor.feature_extractor,
        torch_dtype=dtype,
        device=device,
        chunk_length_s=30,
    )
    result = transcriber(
        str(input_path), return_timestamps=True, generate_kwargs={"task": "transcribe"}
    )
    chunks = result.get("chunks") or []
    segments = []
    for chunk in chunks:
        timestamp = chunk.get("timestamp") or (0.0, 0.0)
        start = float(timestamp[0] or 0.0)
        end = float(timestamp[1] or start)
        text = str(chunk.get("text", "")).strip()
        if text:
            segments.append({"start": start, "end": end, "text": text})
    if not segments and str(result.get("text", "")).strip():
        segments = [{"start": 0.0, "end": 0.0, "text": str(result["text"]).strip()}]
    payload = {"language": "auto", "segments": segments}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.input, args.model, args.output)


if __name__ == "__main__":
    main()
