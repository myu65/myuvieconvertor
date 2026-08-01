from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

from .backends import (
    CosyVoice2TTS,
    IdentityTranslator,
    LocalQwenTranslator,
    MockASR,
    MockLipSync,
    MockTranslator,
    MockTTS,
    MuseTalk15LipSync,
    OpenAICompatibleTranslator,
    RuntimePaths,
    TransformersWhisperASR,
)
from .errors import ConfigurationError, VideoAIError
from .models import fetch_models, materialize_models, verify_models
from .pipeline import PipelineRequest, VideoPipeline
from .spcs import render_job_spec
from .util import confined_path

PRODUCTION_MODELS = ["whisper-large-v3", "cosyvoice2-0.5b", "musetalk"]
COSYVOICE2_LANGUAGES = {
    "zh",
    "zh-cn",
    "chinese",
    "中国語",
    "中文",
    "en",
    "en-us",
    "en-gb",
    "english",
    "英語",
    "ja",
    "ja-jp",
    "japanese",
    "日本語",
    "ko",
    "ko-kr",
    "korean",
    "韓国語",
    "朝鮮語",
}


def _add_pipeline_arguments(parser: argparse.ArgumentParser, *, include_text: bool) -> None:
    parser.add_argument("--avatar", type=Path, required=True, help="Source video or still image")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--target-language", required=True, help="Language name or BCP-47 code")
    parser.add_argument(
        "--voice-reference", type=Path, required=True, help="3-30s clean reference speech"
    )
    parser.add_argument(
        "--voice-transcript", required=True, help="Exact transcript of --voice-reference"
    )
    parser.add_argument("--profile", choices=["production", "mock"], default="production")
    parser.add_argument("--model-root", type=Path)
    parser.add_argument("--keep-workdir", action="store_true")
    parser.add_argument(
        "--duration-policy",
        choices=["preserve", "speech"],
        default="speech" if include_text else "preserve",
        help="Preserve source-video duration or let generated speech determine duration",
    )
    if include_text:
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument("--text")
        group.add_argument("--text-file", type=Path)
    else:
        parser.add_argument("--translator", choices=["qwen", "openai", "identity"], default="qwen")
        parser.add_argument(
            "--translator-base-url", default=os.getenv("VIDEOAI_TRANSLATOR_BASE_URL", "")
        )
        parser.add_argument("--translator-model", default=os.getenv("VIDEOAI_TRANSLATOR_MODEL", ""))
        parser.add_argument(
            "--translator-api-key", default=os.getenv("VIDEOAI_TRANSLATOR_API_KEY", "")
        )


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="videoai")
    root.add_argument("--version", action="version", version="%(prog)s 0.1.0")
    commands = root.add_subparsers(dest="command", required=True)

    dub = commands.add_parser(
        "dub", help="Transcribe, translate, clone voice, and lip-sync a video"
    )
    _add_pipeline_arguments(dub, include_text=False)

    talk = commands.add_parser("talk", help="Make a still image or video speak supplied text")
    _add_pipeline_arguments(talk, include_text=True)

    job = commands.add_parser(
        "run-job", help="Run a validated JSON request, including from an SPCS stage"
    )
    job.add_argument("--request", type=Path, required=True)
    job.add_argument("--output-root", type=Path, required=True)

    doctor = commands.add_parser(
        "doctor", help="Check local runtime, upstream sources, and model files"
    )
    doctor.add_argument("--model-root", type=Path)
    doctor.add_argument("--translator", choices=["qwen", "openai", "identity"], default="qwen")
    doctor.add_argument("--strict", action="store_true")

    models = commands.add_parser("models", help="Fetch, verify, or materialize model snapshots")
    model_commands = models.add_subparsers(dest="models_command", required=True)
    fetch = model_commands.add_parser("fetch")
    fetch.add_argument("--destination", type=Path, required=True)
    fetch.add_argument("--without-qwen", action="store_true")
    verify = model_commands.add_parser("verify")
    verify.add_argument("--root", type=Path, required=True)
    verify.add_argument("--without-qwen", action="store_true")
    materialize = model_commands.add_parser("materialize")
    materialize.add_argument("--source", type=Path, required=True)
    materialize.add_argument("--destination", type=Path, required=True)
    materialize.add_argument("--without-qwen", action="store_true")

    spcs = commands.add_parser(
        "spcs", help="Render a Snowpark Container Services job specification"
    )
    spcs_commands = spcs.add_subparsers(dest="spcs_command", required=True)
    render = spcs_commands.add_parser("render-job-spec")
    render.add_argument("--image", required=True)
    render.add_argument("--model-stage", required=True)
    render.add_argument("--job-stage", required=True)
    render.add_argument("--request-path", required=True)
    render.add_argument("--output", type=Path, required=True)
    render.add_argument("--memory", default="20Gi")
    render.add_argument("--cpu", default="4")
    return root


def _model_names(include_qwen: bool) -> list[str]:
    return PRODUCTION_MODELS + (["qwen3-4b-instruct-2507"] if include_qwen else [])


def _validate_production_language(language: str, profile: str) -> None:
    if profile == "production" and language.strip().lower() not in COSYVOICE2_LANGUAGES:
        raise ConfigurationError(
            "the pinned CosyVoice2 production profile supports Chinese, English, Japanese, "
            "and Korean; "
            f"unsupported target language: {language!r}"
        )


def _runtime_model_root(requested: Path | None, translator: str) -> Path:
    source = requested or Path(os.getenv("VIDEOAI_MODEL_ROOT", "models"))
    if os.getenv("VIDEOAI_MATERIALIZE_MODELS", "0") != "1":
        return source
    destination = Path(os.getenv("VIDEOAI_MODEL_CACHE", str(Path.cwd() / ".videoai-model-cache")))
    marker = destination / ".complete"
    names = _model_names(translator == "qwen")
    expected_marker = "\n".join(sorted(names)) + "\n"
    ready = marker.is_file() and marker.read_text(encoding="utf-8") == expected_marker
    if not ready or verify_models(destination, names):
        materialize_models(source, destination, names)
        marker.write_text(expected_marker, encoding="utf-8")
    return destination


def _pipeline(
    profile: str, translator: str, model_root: Path | None, args: argparse.Namespace
) -> VideoPipeline:
    if profile == "mock":
        return VideoPipeline(MockASR(), MockTranslator(), MockTTS(), MockLipSync())
    resolved_root = _runtime_model_root(model_root, translator)
    runtime = RuntimePaths.from_environment(resolved_root)
    if translator == "qwen":
        translator_backend = LocalQwenTranslator(runtime)
    elif translator == "openai":
        translator_backend = OpenAICompatibleTranslator(
            args.translator_base_url,
            args.translator_api_key,
            args.translator_model,
        )
    else:
        translator_backend = IdentityTranslator()
    return VideoPipeline(
        TransformersWhisperASR(runtime),
        translator_backend,
        CosyVoice2TTS(runtime),
        MuseTalk15LipSync(runtime),
    )


def _run_direct(args: argparse.Namespace) -> int:
    mode = args.command
    text = None
    translator = getattr(args, "translator", "identity")
    _validate_production_language(args.target_language, args.profile)
    if mode == "talk":
        text = args.text if args.text is not None else args.text_file.read_text(encoding="utf-8")
    pipeline = _pipeline(args.profile, translator, args.model_root, args)
    result = pipeline.run(
        PipelineRequest(
            mode=mode,
            avatar=args.avatar,
            output=args.output,
            target_language=args.target_language,
            voice_reference=args.voice_reference,
            voice_transcript=args.voice_transcript,
            text=text,
            profile=args.profile,
            duration_policy=args.duration_policy,
            keep_workdir=args.keep_workdir,
        )
    )
    print(
        json.dumps(
            {"output": str(result.output), "manifest": str(result.manifest)}, ensure_ascii=False
        )
    )
    return 0


def _run_job(args: argparse.Namespace) -> int:
    request_file = args.request.resolve(strict=True)
    request_root = request_file.parent
    payload = json.loads(request_file.read_text(encoding="utf-8"))
    allowed = {
        "mode",
        "avatar",
        "output",
        "target_language",
        "voice_reference",
        "voice_transcript",
        "text",
        "text_file",
        "translator",
        "profile",
        "translator_base_url",
        "translator_model",
        "duration_policy",
    }
    unknown = set(payload) - allowed
    if unknown:
        raise ConfigurationError(f"unknown job request fields: {', '.join(sorted(unknown))}")
    mode = str(payload.get("mode", "dub"))
    output_name = str(payload.get("output", f"{request_file.parent.name}.mp4"))
    if Path(output_name).name != output_name or Path(output_name).suffix.lower() != ".mp4":
        raise ConfigurationError("job output must be a simple .mp4 filename")
    profile = str(payload.get("profile", "production"))
    _validate_production_language(str(payload["target_language"]), profile)
    translator = str(payload.get("translator", "qwen" if mode == "dub" else "identity"))
    namespace = argparse.Namespace(
        translator_base_url=str(
            payload.get("translator_base_url", os.getenv("VIDEOAI_TRANSLATOR_BASE_URL", ""))
        ),
        translator_model=str(
            payload.get("translator_model", os.getenv("VIDEOAI_TRANSLATOR_MODEL", ""))
        ),
        translator_api_key=os.getenv("VIDEOAI_TRANSLATOR_API_KEY", ""),
    )
    text = payload.get("text")
    if payload.get("text_file"):
        text = confined_path(request_root, str(payload["text_file"])).read_text(encoding="utf-8")
    pipeline = _pipeline(profile, translator, None, namespace)
    output = args.output_root.resolve(strict=False) / request_file.parent.name / output_name
    result = pipeline.run(
        PipelineRequest(
            mode=mode,
            avatar=confined_path(request_root, str(payload["avatar"])),
            output=output,
            target_language=str(payload["target_language"]),
            voice_reference=confined_path(request_root, str(payload["voice_reference"])),
            voice_transcript=str(payload["voice_transcript"]),
            text=str(text) if text is not None else None,
            profile=profile,
            duration_policy=str(
                payload.get("duration_policy", "preserve" if mode == "dub" else "speech")
            ),
        )
    )
    print(
        json.dumps(
            {"output": str(result.output), "manifest": str(result.manifest)}, ensure_ascii=False
        )
    )
    return 0


def _doctor(args: argparse.Namespace) -> int:
    root = args.model_root or Path(os.getenv("VIDEOAI_MODEL_ROOT", "models"))
    missing = verify_models(root, _model_names(args.translator == "qwen"))
    report = {
        "python": sys.version.split()[0],
        "ffmpeg": shutil.which("ffmpeg"),
        "ffprobe": shutil.which("ffprobe"),
        "nvidia_smi": shutil.which("nvidia-smi"),
        "upstreams": {
            "CosyVoice": (
                Path(os.getenv("VIDEOAI_UPSTREAM_ROOT", "/opt/upstreams")) / "CosyVoice"
            ).is_dir(),
            "MuseTalk": (
                Path(os.getenv("VIDEOAI_UPSTREAM_ROOT", "/opt/upstreams")) / "MuseTalk"
            ).is_dir(),
        },
        "missing_models": missing,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    failed = (
        not report["ffmpeg"]
        or not report["ffprobe"]
        or bool(missing)
        or not all(report["upstreams"].values())
    )
    return 1 if args.strict and failed else 0


def dispatch(args: argparse.Namespace) -> int:
    if args.command in {"dub", "talk"}:
        return _run_direct(args)
    if args.command == "run-job":
        return _run_job(args)
    if args.command == "doctor":
        return _doctor(args)
    if args.command == "models":
        names = _model_names(not args.without_qwen)
        if args.models_command == "fetch":
            print(fetch_models(args.destination, names))
            return 0
        if args.models_command == "verify":
            missing = verify_models(args.root, names)
            print(json.dumps({"ok": not missing, "missing": missing}, indent=2))
            return 1 if missing else 0
        materialize_models(args.source, args.destination, names)
        print(args.destination)
        return 0
    if args.command == "spcs":
        spec = render_job_spec(
            image=args.image,
            model_stage=args.model_stage,
            job_stage=args.job_stage,
            request_path=args.request_path,
            memory=args.memory,
            cpu=args.cpu,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(spec, encoding="utf-8")
        print(args.output)
        return 0
    raise AssertionError(args.command)


def main(argv: list[str] | None = None) -> None:
    try:
        raise SystemExit(dispatch(parser().parse_args(argv)))
    except (VideoAIError, KeyError, json.JSONDecodeError, OSError) as exc:
        print(f"videoai: error: {exc}", file=sys.stderr)
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
