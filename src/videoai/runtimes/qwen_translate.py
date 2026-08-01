from __future__ import annotations

import argparse
import json
from pathlib import Path


def _extract_array(value: str) -> list[dict[str, object]]:
    value = value.strip()
    if value.startswith("```"):
        value = value.split("\n", 1)[1].rsplit("```", 1)[0]
    start = value.find("[")
    end = value.rfind("]")
    if start < 0 or end <= start:
        raise ValueError("model did not return a JSON array")
    parsed = json.loads(value[start : end + 1])
    if not isinstance(parsed, list):
        raise ValueError("model response is not a JSON array")
    return parsed


def run(input_path: Path, target_language: str, model_path: Path, output: Path) -> None:
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    source = json.loads(input_path.read_text(encoding="utf-8"))
    segments = source.get("segments") or []
    rows = [{"id": index, "text": item["text"]} for index, item in enumerate(segments)]
    prompt = (
        f"Translate each row to {target_language}. Return only JSON with the same ids and "
        "non-empty text. "
        "Preserve names, numbers, meaning, and tone. Do not merge or add rows.\n"
        + json.dumps(rows, ensure_ascii=False)
    )
    tokenizer = AutoTokenizer.from_pretrained(model_path)
    model = AutoModelForCausalLM.from_pretrained(
        model_path,
        torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32,
        device_map="auto",
    )
    messages = [
        {"role": "system", "content": "You are a precise translation engine."},
        {"role": "user", "content": prompt},
    ]
    inputs = tokenizer.apply_chat_template(
        messages,
        add_generation_prompt=True,
        tokenize=True,
        return_dict=True,
        return_tensors="pt",
    ).to(model.device)
    generated = model.generate(**inputs, max_new_tokens=max(512, len(rows) * 96), do_sample=False)
    answer = tokenizer.decode(
        generated[0][inputs["input_ids"].shape[-1] :], skip_special_tokens=True
    )
    translated = _extract_array(answer)
    by_id = {int(item["id"]): str(item["text"]).strip() for item in translated}
    if set(by_id) != set(range(len(rows))) or any(not value for value in by_id.values()):
        raise ValueError("model changed ids or returned empty translations")
    payload = {
        "language": target_language,
        "segments": [
            {"start": item["start"], "end": item["end"], "text": by_id[index]}
            for index, item in enumerate(segments)
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--target-language", required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.input, args.target_language, args.model, args.output)


if __name__ == "__main__":
    main()
