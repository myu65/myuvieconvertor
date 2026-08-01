from __future__ import annotations

import contextlib
import os
import shutil
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

from .backends import ASR, TTS, LipSync, Translator
from .errors import ConfigurationError
from .manifest import RunManifest
from .media import (
    AUDIO_SUFFIXES,
    IMAGE_SUFFIXES,
    VIDEO_SUFFIXES,
    extract_audio,
    match_audio_duration,
    media_duration,
    normalize_audio,
    normalize_avatar,
)
from .types import Transcript
from .util import json_dump, require_artifact, stage_safe_copy


@dataclass(frozen=True)
class PipelineRequest:
    mode: str
    avatar: Path
    output: Path
    target_language: str
    voice_reference: Path
    voice_transcript: str
    text: str | None = None
    source_language: str | None = None
    profile: str = "production"
    duration_policy: str = "preserve"
    keep_workdir: bool = False


@dataclass(frozen=True)
class PipelineResult:
    output: Path
    manifest: Path
    transcript: Path | None
    translated_transcript: Path


class VideoPipeline:
    def __init__(self, asr: ASR, translator: Translator, tts: TTS, lipsync: LipSync) -> None:
        self.asr = asr
        self.translator = translator
        self.tts = tts
        self.lipsync = lipsync

    def run(self, request: PipelineRequest) -> PipelineResult:
        self._validate(request)
        run_id = uuid.uuid4().hex[:16]
        work_root = Path(os.getenv("VIDEOAI_WORK_ROOT", tempfile.gettempdir()))
        workdir = work_root / f"videoai-{run_id}"
        workdir.mkdir(parents=True, exist_ok=False)
        manifest = RunManifest(
            run_id=run_id,
            mode=request.mode,
            profile=request.profile,
            target_language=request.target_language,
        )
        manifest.add_input("avatar", request.avatar)
        manifest.add_input("voice_reference", request.voice_reference)
        transcript_path: Path | None = None
        final_source_transcript: Path | None = None
        final_manifest = request.output.with_suffix(request.output.suffix + ".manifest.json")
        final_translated = request.output.with_suffix(request.output.suffix + ".transcript.json")
        try:
            safe_avatar = workdir / f"avatar{request.avatar.suffix.lower()}"
            safe_voice = workdir / "voice-reference.wav"
            shutil.copyfile(request.avatar, safe_avatar)
            normalize_audio(
                request.voice_reference, safe_voice
            ) if request.profile != "mock" else shutil.copyfile(request.voice_reference, safe_voice)

            if request.mode == "dub":
                step = manifest.step("transcribe")
                try:
                    source_audio = workdir / "source.wav"
                    if request.profile == "mock":
                        shutil.copyfile(safe_voice, source_audio)
                    else:
                        extract_audio(safe_avatar, source_audio)
                    transcript = self.asr.transcribe(source_audio, workdir)
                    transcript_path = workdir / "source-transcript.json"
                    json_dump(transcript_path, transcript.to_dict())
                    step.finish(language=transcript.language, segments=len(transcript.segments))
                except Exception as exc:
                    step.fail(str(exc))
                    raise
                step = manifest.step("translate")
                try:
                    translated = self.translator.translate(
                        transcript, request.target_language, workdir
                    )
                    step.finish(language=translated.language, segments=len(translated.segments))
                except Exception as exc:
                    step.fail(str(exc))
                    raise
            else:
                translated = Transcript.from_dict(
                    {
                        "language": request.target_language,
                        "segments": [{"start": 0.0, "end": 0.0, "text": request.text or ""}],
                    }
                )

            translated_work = workdir / "translated-transcript.json"
            json_dump(translated_work, translated.to_dict())

            step = manifest.step("synthesize")
            try:
                speech_raw = workdir / "speech-raw.wav"
                self.tts.synthesize(
                    translated.text,
                    safe_voice,
                    request.voice_transcript,
                    speech_raw,
                    workdir,
                )
                speech = workdir / "speech.wav"
                if request.profile == "mock":
                    shutil.copyfile(speech_raw, speech)
                else:
                    normalize_audio(speech_raw, speech)
                step.finish(bytes=speech.stat().st_size)
            except Exception as exc:
                step.fail(str(exc))
                raise

            step = manifest.step("prepare-avatar")
            try:
                if request.mode == "dub" and request.duration_policy == "preserve":
                    aligned = workdir / "speech-aligned.wav"
                    if request.profile == "mock":
                        shutil.copyfile(speech, aligned)
                    else:
                        match_audio_duration(speech, media_duration(safe_avatar), aligned)
                    speech = aligned
                prepared_avatar = workdir / "avatar-25fps.mp4"
                if request.profile == "mock":
                    shutil.copyfile(safe_avatar, prepared_avatar)
                else:
                    normalize_avatar(safe_avatar, speech, prepared_avatar)
                step.finish(bytes=prepared_avatar.stat().st_size)
            except Exception as exc:
                step.fail(str(exc))
                raise

            step = manifest.step("lip-sync")
            try:
                rendered = workdir / "rendered.mp4"
                self.lipsync.render(prepared_avatar, speech, rendered, workdir)
                require_artifact(rendered, "final rendered video", minimum_bytes=1024)
                step.finish(bytes=rendered.stat().st_size)
            except Exception as exc:
                step.fail(str(exc))
                raise

            stage_safe_copy(rendered, request.output)
            stage_safe_copy(translated_work, final_translated)
            if transcript_path is not None:
                final_source_transcript = request.output.with_suffix(
                    request.output.suffix + ".source-transcript.json"
                )
                stage_safe_copy(transcript_path, final_source_transcript)
                manifest.add_output("source_transcript", final_source_transcript)
            manifest.add_output("video", request.output)
            manifest.add_output("translated_transcript", final_translated)
            manifest.write(workdir / "manifest.json")
            stage_safe_copy(workdir / "manifest.json", final_manifest)
            return PipelineResult(
                output=request.output,
                manifest=final_manifest,
                transcript=final_source_transcript,
                translated_transcript=final_translated,
            )
        except Exception:
            failed = workdir / "manifest.failed.json"
            manifest.write(failed)
            with contextlib.suppress(OSError):
                stage_safe_copy(
                    failed,
                    request.output.with_suffix(request.output.suffix + ".failed.manifest.json"),
                )
            raise
        finally:
            if not request.keep_workdir:
                shutil.rmtree(workdir, ignore_errors=True)

    @staticmethod
    def _validate(request: PipelineRequest) -> None:
        if request.mode not in {"dub", "talk"}:
            raise ConfigurationError("mode must be dub or talk")
        if request.duration_policy not in {"preserve", "speech"}:
            raise ConfigurationError("duration policy must be preserve or speech")
        if not request.avatar.is_file():
            raise ConfigurationError(f"avatar input does not exist: {request.avatar}")
        if request.avatar.suffix.lower() not in VIDEO_SUFFIXES | IMAGE_SUFFIXES:
            raise ConfigurationError(f"unsupported avatar extension: {request.avatar.suffix}")
        if request.mode == "dub" and request.avatar.suffix.lower() not in VIDEO_SUFFIXES:
            raise ConfigurationError(
                "dub mode requires a video with source audio; use talk for a still image"
            )
        if not request.voice_reference.is_file():
            raise ConfigurationError(f"voice reference does not exist: {request.voice_reference}")
        if request.voice_reference.suffix.lower() not in AUDIO_SUFFIXES:
            raise ConfigurationError(
                f"unsupported voice reference extension: {request.voice_reference.suffix}"
            )
        if not request.voice_transcript.strip():
            raise ConfigurationError("an exact transcript of the voice reference is required")
        if request.mode == "talk" and not (request.text or "").strip():
            raise ConfigurationError("talk mode requires text")
        if not request.target_language.strip():
            raise ConfigurationError("target language is required")
        request.output.parent.mkdir(parents=True, exist_ok=True)
        if request.output.resolve(strict=False) in {
            request.avatar.resolve(strict=True),
            request.voice_reference.resolve(strict=True),
        }:
            raise ConfigurationError("output must not overwrite an input")
