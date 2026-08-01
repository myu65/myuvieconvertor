from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


def _yaml_string(value: str) -> str:
    import json

    return json.dumps(value, ensure_ascii=False)


def run(
    avatar: Path,
    audio: Path,
    model_root: Path,
    repo: Path,
    work_dir: Path,
    output: Path,
    fps: int,
    batch_size: int,
) -> None:
    if not repo.is_dir():
        raise FileNotFoundError(f"MuseTalk source directory not found: {repo}")
    required = [
        "musetalkV15/musetalk.json",
        "musetalkV15/unet.pth",
        "sd-vae/config.json",
        "whisper/config.json",
        "face-parse-bisent/79999_iter.pth",
    ]
    missing = [item for item in required if not (model_root / item).is_file()]
    if missing:
        raise FileNotFoundError(f"MuseTalk model directory is incomplete: {', '.join(missing)}")
    work_dir.mkdir(parents=True, exist_ok=True)
    model_link = work_dir / "models"
    if not model_link.exists():
        model_link.symlink_to(model_root, target_is_directory=True)
    config = work_dir / "inference.yaml"
    config.write_text(
        "videoai:\n"
        f"  video_path: {_yaml_string(str(avatar))}\n"
        f"  audio_path: {_yaml_string(str(audio))}\n"
        "  result_name: videoai-output.mp4\n",
        encoding="utf-8",
    )
    result_dir = work_dir / "results"
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise FileNotFoundError("ffmpeg is required")
    command = [
        sys.executable,
        "-m",
        "scripts.inference",
        "--inference_config",
        str(config),
        "--result_dir",
        str(result_dir),
        "--unet_model_path",
        str(model_root / "musetalkV15" / "unet.pth"),
        "--unet_config",
        str(model_root / "musetalkV15" / "musetalk.json"),
        "--whisper_dir",
        str(model_root / "whisper"),
        "--version",
        "v15",
        "--fps",
        str(fps),
        "--batch_size",
        str(batch_size),
        "--use_float16",
        "--ffmpeg_path",
        str(Path(ffmpeg).parent),
    ]
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join([str(repo), os.environ.get("PYTHONPATH", "")]),
    }
    completed = subprocess.run(
        command,
        cwd=work_dir,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=14400,
    )
    generated = result_dir / "v15" / "videoai-output.mp4"
    # Upstream catches processing exceptions and can exit zero, so verify the artifact.
    if completed.returncode != 0 or not generated.is_file() or generated.stat().st_size < 1024:
        tail = "\n".join((completed.stderr + "\n" + completed.stdout).splitlines()[-80:])
        raise RuntimeError(
            f"MuseTalk failed to create output (exit={completed.returncode})\n{tail}"
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(generated, output)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--avatar", type=Path, required=True)
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--model-root", type=Path, required=True)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fps", type=int, default=25)
    parser.add_argument("--batch-size", type=int, default=8)
    args = parser.parse_args()
    run(
        args.avatar,
        args.audio,
        args.model_root,
        args.repo,
        args.work_dir,
        args.output,
        args.fps,
        args.batch_size,
    )


if __name__ == "__main__":
    main()
