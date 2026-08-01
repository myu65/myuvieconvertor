import shutil
import subprocess
from pathlib import Path

import pytest

from videoai.media import _atempo_chain, audio_duration, match_audio_duration


@pytest.mark.parametrize("ratio", [0.1, 0.5, 1.0, 2.0, 8.0])
def test_atempo_chain_factors_are_supported(ratio: float) -> None:
    factors = [float(item.split("=")[1]) for item in _atempo_chain(ratio).split(",")]
    assert all(0.5 <= item <= 2.0 for item in factors)
    product = 1.0
    for item in factors:
        product *= item
    assert product == pytest.approx(ratio)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg unavailable")
def test_duration_alignment(tmp_path: Path) -> None:
    source = tmp_path / "source.wav"
    output = tmp_path / "output.wav"
    subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1",
            str(source),
        ],
        check=True,
    )
    match_audio_duration(source, 2.0, output)
    assert audio_duration(output) == pytest.approx(2.0, abs=0.03)
