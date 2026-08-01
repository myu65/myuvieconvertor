from __future__ import annotations

import json
import shutil
from pathlib import Path

from .errors import ConfigurationError
from .util import require_artifact, run_command

VIDEO_SUFFIXES = {".mp4", ".mov", ".mkv", ".webm", ".avi"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
AUDIO_SUFFIXES = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".aac"}


def require_binary(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise ConfigurationError(f"required executable is unavailable: {name}")
    return path


def extract_audio(media: Path, output: Path) -> Path:
    ffmpeg = require_binary("ffmpeg")
    run_command(
        [
            ffmpeg,
            "-nostdin",
            "-y",
            "-v",
            "error",
            "-i",
            str(media),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            str(output),
        ],
        timeout=3600,
    )
    return require_artifact(output, "audio extraction", minimum_bytes=44)


def audio_duration(audio: Path) -> float:
    ffprobe = require_binary("ffprobe")
    result = run_command(
        [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "json", str(audio)],
        timeout=60,
    )
    duration = float(json.loads(result.stdout)["format"]["duration"])
    if duration <= 0:
        raise ConfigurationError(f"audio has invalid duration: {audio}")
    return duration


def media_duration(media: Path) -> float:
    return audio_duration(media)


def _atempo_chain(ratio: float) -> str:
    if ratio <= 0:
        raise ConfigurationError("tempo ratio must be positive")
    factors: list[float] = []
    while ratio > 2.0:
        factors.append(2.0)
        ratio /= 2.0
    while ratio < 0.5:
        factors.append(0.5)
        ratio /= 0.5
    factors.append(ratio)
    return ",".join(f"atempo={item:.8f}" for item in factors)


def match_audio_duration(audio: Path, target_seconds: float, output: Path) -> Path:
    source_seconds = audio_duration(audio)
    if target_seconds <= 0:
        raise ConfigurationError("target media has invalid duration")
    tempo = source_seconds / target_seconds
    ffmpeg = require_binary("ffmpeg")
    audio_filter = f"{_atempo_chain(tempo)},apad,atrim=0:{target_seconds:.6f}"
    run_command(
        [
            ffmpeg,
            "-nostdin",
            "-y",
            "-v",
            "error",
            "-i",
            str(audio),
            "-filter:a",
            audio_filter,
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            str(output),
        ],
        timeout=3600,
    )
    return require_artifact(output, "duration-aligned audio", minimum_bytes=44)


def normalize_audio(audio: Path, output: Path) -> Path:
    ffmpeg = require_binary("ffmpeg")
    run_command(
        [
            ffmpeg,
            "-nostdin",
            "-y",
            "-v",
            "error",
            "-i",
            str(audio),
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            str(output),
        ],
        timeout=3600,
    )
    return require_artifact(output, "audio normalization", minimum_bytes=44)


def normalize_avatar(avatar: Path, audio: Path, output: Path, fps: int = 25) -> Path:
    ffmpeg = require_binary("ffmpeg")
    suffix = avatar.suffix.lower()
    common = [ffmpeg, "-nostdin", "-y", "-v", "error"]
    if suffix in IMAGE_SUFFIXES:
        duration = audio_duration(audio)
        command = [
            *common,
            "-loop",
            "1",
            "-i",
            str(avatar),
            "-t",
            f"{duration:.3f}",
            "-r",
            str(fps),
            "-vf",
            "scale=trunc(iw/2)*2:trunc(ih/2)*2,format=yuv420p",
            "-an",
            "-c:v",
            "libx264",
            str(output),
        ]
    elif suffix in VIDEO_SUFFIXES:
        command = [
            *common,
            "-i",
            str(avatar),
            "-an",
            "-r",
            str(fps),
            "-vf",
            "scale=trunc(iw/2)*2:trunc(ih/2)*2,format=yuv420p",
            "-c:v",
            "libx264",
            str(output),
        ]
    else:
        raise ConfigurationError(f"unsupported avatar format: {suffix}")
    run_command(command, timeout=7200)
    return require_artifact(output, "avatar normalization", minimum_bytes=1024)
