import argparse
import json
from pathlib import Path

import pytest

from videoai import cli


def _media(path: Path) -> Path:
    path.write_bytes(b"x" * 2048)
    return path


def test_dispatch_talk_mock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VIDEOAI_WORK_ROOT", str(tmp_path / "work"))
    avatar = _media(tmp_path / "avatar.png")
    voice = _media(tmp_path / "voice.wav")
    output = tmp_path / "result.mp4"
    args = cli.parser().parse_args(
        [
            "talk",
            "--avatar",
            str(avatar),
            "--voice-reference",
            str(voice),
            "--voice-transcript",
            "reference",
            "--target-language",
            "ja",
            "--text",
            "こんにちは",
            "--profile",
            "mock",
            "--output",
            str(output),
        ]
    )
    assert cli.dispatch(args) == 0
    assert output.stat().st_size == avatar.stat().st_size


def test_dispatch_mock_job_and_reject_unknown_field(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VIDEOAI_WORK_ROOT", str(tmp_path / "work"))
    request_dir = tmp_path / "requests" / "job-1"
    request_dir.mkdir(parents=True)
    _media(request_dir / "avatar.mp4")
    _media(request_dir / "voice.wav")
    request = request_dir / "request.json"
    payload = {
        "mode": "dub",
        "avatar": "avatar.mp4",
        "output": "done.mp4",
        "target_language": "en",
        "voice_reference": "voice.wav",
        "voice_transcript": "reference",
        "profile": "mock",
    }
    request.write_text(json.dumps(payload), encoding="utf-8")
    args = argparse.Namespace(request=request, output_root=tmp_path / "outputs")
    assert cli._run_job(args) == 0
    assert (tmp_path / "outputs" / "job-1" / "done.mp4").is_file()

    payload["unexpected"] = True
    request.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(cli.ConfigurationError, match="unknown job request fields"):
        cli._run_job(args)


def test_dispatch_spcs_and_models_verify(tmp_path: Path) -> None:
    spec_path = tmp_path / "job.yaml"
    spec_args = cli.parser().parse_args(
        [
            "spcs",
            "render-job-spec",
            "--image",
            "/DB/SCHEMA/IMAGES/videoai:sha",
            "--model-stage",
            "@DB.SCHEMA.MODELS",
            "--job-stage",
            "@DB.SCHEMA.JOBS",
            "--request-path",
            "requests/job-1/request.json",
            "--output",
            str(spec_path),
        ]
    )
    assert cli.dispatch(spec_args) == 0
    assert "nvidia.com/gpu: 1" in spec_path.read_text(encoding="utf-8")

    verify_args = cli.parser().parse_args(
        ["models", "verify", "--root", str(tmp_path / "models"), "--without-qwen"]
    )
    assert cli.dispatch(verify_args) == 1


def test_doctor_and_main_error_path(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    args = argparse.Namespace(model_root=tmp_path / "missing", translator="identity", strict=False)
    assert cli._doctor(args) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["missing_models"]

    with pytest.raises(SystemExit) as raised:
        cli.main(
            [
                "spcs",
                "render-job-spec",
                "--image",
                "invalid\nimage",
                "--model-stage",
                "@DB.SCHEMA.MODELS",
                "--job-stage",
                "@DB.SCHEMA.JOBS",
                "--request-path",
                "request.json",
                "--output",
                str(tmp_path / "bad.yaml"),
            ]
        )
    assert raised.value.code == 2
    assert "videoai: error:" in capsys.readouterr().err


def test_production_language_and_pipeline_selection(tmp_path: Path) -> None:
    cli._validate_production_language("日本語", "production")
    with pytest.raises(cli.ConfigurationError, match="unsupported target language"):
        cli._validate_production_language("fr", "production")

    args = argparse.Namespace(
        translator_base_url="https://example.com/v1",
        translator_api_key="",
        translator_model="test-model",
    )
    pipeline = cli._pipeline("production", "identity", tmp_path / "models", args)
    assert pipeline.translator.__class__.__name__ == "IdentityTranslator"
