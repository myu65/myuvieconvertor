from pathlib import Path

import pytest

from videoai.backends import MockASR, MockLipSync, MockTranslator, MockTTS
from videoai.errors import ConfigurationError
from videoai.pipeline import PipelineRequest, VideoPipeline


def _file(path: Path, size: int = 2048) -> Path:
    path.write_bytes(b"x" * size)
    return path


def test_mock_dub_end_to_end(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VIDEOAI_WORK_ROOT", str(tmp_path / "work"))
    avatar = _file(tmp_path / "avatar.mp4")
    voice = _file(tmp_path / "voice.wav")
    output = tmp_path / "out" / "translated.mp4"
    result = VideoPipeline(MockASR(), MockTranslator(), MockTTS(), MockLipSync()).run(
        PipelineRequest(
            mode="dub",
            avatar=avatar,
            output=output,
            target_language="en",
            voice_reference=voice,
            voice_transcript="これは参照音声です。",
            profile="mock",
        )
    )
    assert result.output.is_file()
    assert result.manifest.is_file()
    assert result.transcript is not None and result.transcript.is_file()
    assert result.translated_transcript.is_file()
    assert "[en]" in result.translated_transcript.read_text(encoding="utf-8")
    assert not any((tmp_path / "work").iterdir())


def test_talk_requires_text(tmp_path: Path) -> None:
    avatar = _file(tmp_path / "avatar.png")
    voice = _file(tmp_path / "voice.wav")
    request = PipelineRequest(
        mode="talk",
        avatar=avatar,
        output=tmp_path / "out.mp4",
        target_language="ja",
        voice_reference=voice,
        voice_transcript="参照",
        profile="mock",
    )
    with pytest.raises(ConfigurationError):
        VideoPipeline(MockASR(), MockTranslator(), MockTTS(), MockLipSync()).run(request)
