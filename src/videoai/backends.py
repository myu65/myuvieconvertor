from __future__ import annotations

import json
import os
import shutil
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .errors import BackendError, ConfigurationError
from .types import Segment, Transcript
from .util import json_dump, json_load, require_artifact, run_command


class ASR(Protocol):
    def transcribe(self, audio: Path, workdir: Path) -> Transcript: ...


class Translator(Protocol):
    def translate(
        self, transcript: Transcript, target_language: str, workdir: Path
    ) -> Transcript: ...


class TTS(Protocol):
    def synthesize(
        self, text: str, voice_reference: Path, voice_transcript: str, output: Path, workdir: Path
    ) -> Path: ...


class LipSync(Protocol):
    def render(self, avatar: Path, audio: Path, output: Path, workdir: Path) -> Path: ...


@dataclass(frozen=True)
class RuntimePaths:
    model_root: Path
    upstream_root: Path = Path("/opt/upstreams")
    whisper_python: str = sys.executable
    cosyvoice_python: str = sys.executable
    musetalk_python: str = sys.executable
    qwen_python: str = sys.executable

    @classmethod
    def from_environment(cls, model_root: Path | None = None) -> RuntimePaths:
        return cls(
            model_root=model_root or Path(os.getenv("VIDEOAI_MODEL_ROOT", "models")),
            upstream_root=Path(os.getenv("VIDEOAI_UPSTREAM_ROOT", "/opt/upstreams")),
            whisper_python=os.getenv("VIDEOAI_WHISPER_PYTHON", sys.executable),
            cosyvoice_python=os.getenv("VIDEOAI_COSYVOICE_PYTHON", sys.executable),
            musetalk_python=os.getenv("VIDEOAI_MUSETALK_PYTHON", sys.executable),
            qwen_python=os.getenv("VIDEOAI_QWEN_PYTHON", sys.executable),
        )


class TransformersWhisperASR:
    def __init__(self, runtime: RuntimePaths, model_name: str = "whisper-large-v3") -> None:
        self.runtime = runtime
        self.model_name = model_name

    def transcribe(self, audio: Path, workdir: Path) -> Transcript:
        output = workdir / "transcript.json"
        run_command(
            [
                self.runtime.whisper_python,
                "-m",
                "videoai.runtimes.whisper",
                "--input",
                str(audio),
                "--model",
                str(self.runtime.model_root / self.model_name),
                "--output",
                str(output),
            ],
            timeout=7200,
        )
        data = json_load(require_artifact(output, "Whisper ASR output"))
        transcript = Transcript.from_dict(data)
        if not transcript.text:
            raise BackendError("Whisper returned an empty transcript")
        return transcript


class IdentityTranslator:
    def translate(self, transcript: Transcript, target_language: str, workdir: Path) -> Transcript:
        del workdir
        return Transcript(language=target_language, segments=transcript.segments)


class OpenAICompatibleTranslator:
    def __init__(self, base_url: str, api_key: str, model: str, timeout: int = 180) -> None:
        if not base_url:
            raise ConfigurationError("translator base URL is required")
        parsed_url = urllib.parse.urlparse(base_url)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            raise ConfigurationError("translator base URL must be an HTTP(S) URL")
        if not model:
            raise ConfigurationError("translator model is required")
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def translate(self, transcript: Transcript, target_language: str, workdir: Path) -> Transcript:
        del workdir
        rows = [{"id": index, "text": item.text} for index, item in enumerate(transcript.segments)]
        prompt = (
            f"Translate every row into {target_language}. Preserve meaning, names, numbers, "
            "and tone. Return only a JSON array with exactly the same integer id values and a "
            "translated text field. "
            "Do not merge, omit, or add rows.\n" + json.dumps(rows, ensure_ascii=False)
        )
        payload = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {
                    "role": "system",
                    "content": "You are a precise enterprise video subtitle translator.",
                },
                {"role": "user", "content": prompt},
            ],
        }
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = urllib.request.Request(  # noqa: S310 - URL scheme validated at construction
            self.url,
            data=json.dumps(payload).encode(),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:  # noqa: S310
                body = json.load(response)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise BackendError(f"translation API request failed: {exc}") from exc
        try:
            content = body["choices"][0]["message"]["content"].strip()
            if content.startswith("```"):
                content = content.split("\n", 1)[1].rsplit("```", 1)[0]
            translated = json.loads(content)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise BackendError(
                "translation API returned an invalid Chat Completions payload"
            ) from exc
        if not isinstance(translated, list) or len(translated) != len(rows):
            raise BackendError("translator changed the number of transcript segments")
        by_id: dict[int, str] = {}
        for item in translated:
            if not isinstance(item, dict) or not isinstance(item.get("id"), int):
                raise BackendError("translator returned a row without an integer id")
            text = item.get("text")
            if not isinstance(text, str) or not text.strip():
                raise BackendError(f"translator returned empty text for id {item.get('id')}")
            if item["id"] in by_id:
                raise BackendError(f"translator returned duplicate id {item['id']}")
            by_id[item["id"]] = text.strip()
        if set(by_id) != set(range(len(rows))):
            raise BackendError("translator changed transcript segment ids")
        return Transcript(
            language=target_language,
            segments=tuple(
                Segment(start=segment.start, end=segment.end, text=by_id[index])
                for index, segment in enumerate(transcript.segments)
            ),
        )


class LocalQwenTranslator:
    def __init__(self, runtime: RuntimePaths, model_name: str = "qwen3-4b-instruct-2507") -> None:
        self.runtime = runtime
        self.model_name = model_name

    def translate(self, transcript: Transcript, target_language: str, workdir: Path) -> Transcript:
        source = workdir / "translate-input.json"
        output = workdir / "translate-output.json"
        json_dump(source, transcript.to_dict())
        run_command(
            [
                self.runtime.qwen_python,
                "-m",
                "videoai.runtimes.qwen_translate",
                "--input",
                str(source),
                "--target-language",
                target_language,
                "--model",
                str(self.runtime.model_root / self.model_name),
                "--output",
                str(output),
            ],
            timeout=7200,
        )
        result = Transcript.from_dict(
            json_load(require_artifact(output, "Qwen translation output"))
        )
        if len(result.segments) != len(transcript.segments) or not result.text:
            raise BackendError("Qwen translator returned an incomplete transcript")
        return result


class CosyVoice2TTS:
    def __init__(self, runtime: RuntimePaths, model_name: str = "cosyvoice2-0.5b") -> None:
        self.runtime = runtime
        self.model_name = model_name

    def synthesize(
        self, text: str, voice_reference: Path, voice_transcript: str, output: Path, workdir: Path
    ) -> Path:
        text_file = workdir / "tts-text.txt"
        prompt_file = workdir / "voice-transcript.txt"
        text_file.write_text(text, encoding="utf-8")
        prompt_file.write_text(voice_transcript, encoding="utf-8")
        run_command(
            [
                self.runtime.cosyvoice_python,
                "-m",
                "videoai.runtimes.cosyvoice2",
                "--text-file",
                str(text_file),
                "--voice-reference",
                str(voice_reference),
                "--voice-transcript-file",
                str(prompt_file),
                "--model",
                str(self.runtime.model_root / self.model_name),
                "--repo",
                str(self.runtime.upstream_root / "CosyVoice"),
                "--output",
                str(output),
            ],
            timeout=7200,
        )
        return require_artifact(output, "CosyVoice2 speech", minimum_bytes=44)


class MuseTalk15LipSync:
    def __init__(self, runtime: RuntimePaths, fps: int = 25, batch_size: int = 8) -> None:
        self.runtime = runtime
        self.fps = fps
        self.batch_size = batch_size

    def render(self, avatar: Path, audio: Path, output: Path, workdir: Path) -> Path:
        run_command(
            [
                self.runtime.musetalk_python,
                "-m",
                "videoai.runtimes.musetalk15",
                "--avatar",
                str(avatar),
                "--audio",
                str(audio),
                "--model-root",
                str(self.runtime.model_root / "musetalk"),
                "--repo",
                str(self.runtime.upstream_root / "MuseTalk"),
                "--work-dir",
                str(workdir / "musetalk"),
                "--output",
                str(output),
                "--fps",
                str(self.fps),
                "--batch-size",
                str(self.batch_size),
            ],
            timeout=14400,
        )
        return require_artifact(output, "MuseTalk video", minimum_bytes=1024)


class MockASR:
    def transcribe(self, audio: Path, workdir: Path) -> Transcript:
        del audio, workdir
        return Transcript(language="ja", segments=(Segment(0.0, 1.0, "テスト音声です。"),))


class MockTranslator:
    def translate(self, transcript: Transcript, target_language: str, workdir: Path) -> Transcript:
        del workdir
        return Transcript(
            language=target_language,
            segments=tuple(
                Segment(item.start, item.end, f"[{target_language}] {item.text}")
                for item in transcript.segments
            ),
        )


class MockTTS:
    def synthesize(
        self, text: str, voice_reference: Path, voice_transcript: str, output: Path, workdir: Path
    ) -> Path:
        del text, voice_reference, voice_transcript, workdir
        output.write_bytes(b"RIFF" + b"\x00" * 64)
        return output


class MockLipSync:
    def render(self, avatar: Path, audio: Path, output: Path, workdir: Path) -> Path:
        del audio, workdir
        if avatar.is_file() and avatar.stat().st_size >= 1024:
            shutil.copyfile(avatar, output)
        else:
            output.write_bytes(b"mock-video" * 200)
        return output
