# syntax=docker/dockerfile:1.7
FROM nvidia/cuda:12.1.1-cudnn8-runtime-ubuntu22.04 AS runtime

ARG DEBIAN_FRONTEND=noninteractive
ARG MUSETALK_REVISION=0a89dec45a0192b824e3cf4daf96c239440c5ed8
ARG COSYVOICE_REVISION=3bf48f125a8c25d3f9c386cdb3abf2b614391817

RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential ffmpeg git libgl1 libglib2.0-0 libsndfile1 libsox-dev \
      python3.10 python3.10-dev python3.10-venv sox ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/videoai-src
COPY pyproject.toml README.md LICENSE ./
COPY src ./src

# Lightweight orchestration environment.
RUN python3.10 -m venv /opt/venvs/videoai \
    && /opt/venvs/videoai/bin/pip install --no-cache-dir --upgrade pip setuptools wheel \
    && /opt/venvs/videoai/bin/pip install --no-cache-dir .

# Fetch source only; model weights are deliberately supplied at runtime from a mounted directory/Stage.
RUN mkdir -p /opt/upstreams \
    && git init /opt/upstreams/MuseTalk \
    && git -C /opt/upstreams/MuseTalk remote add origin https://github.com/TMElyralab/MuseTalk.git \
    && git -C /opt/upstreams/MuseTalk fetch --depth 1 origin ${MUSETALK_REVISION} \
    && git -C /opt/upstreams/MuseTalk checkout --detach FETCH_HEAD \
    && rm -rf /opt/upstreams/MuseTalk/.git \
    && git init /opt/upstreams/CosyVoice \
    && git -C /opt/upstreams/CosyVoice remote add origin https://github.com/FunAudioLLM/CosyVoice.git \
    && git -C /opt/upstreams/CosyVoice fetch --depth 1 origin ${COSYVOICE_REVISION} \
    && git -C /opt/upstreams/CosyVoice checkout --detach FETCH_HEAD \
    && git -C /opt/upstreams/CosyVoice submodule update --init --depth 1 \
    && rm -rf /opt/upstreams/CosyVoice/.git

# Whisper large-v3 runtime. A separate venv keeps upstream dependency pins isolated.
RUN python3.10 -m venv /opt/venvs/whisper \
    && /opt/venvs/whisper/bin/pip install --no-cache-dir --upgrade pip wheel \
    && /opt/venvs/whisper/bin/pip install --no-cache-dir \
       torch==2.3.1 torchaudio==2.3.1 --index-url https://download.pytorch.org/whl/cu121 \
    && /opt/venvs/whisper/bin/pip install --no-cache-dir \
       accelerate==0.30.1 librosa==0.10.2 soundfile==0.12.1 transformers==4.40.1 \
    && /opt/venvs/whisper/bin/pip install --no-cache-dir --no-deps /opt/videoai-src

# CosyVoice2 runtime, pinned to the last verified CosyVoice2-era source revision.
RUN python3.10 -m venv /opt/venvs/cosyvoice \
    && /opt/venvs/cosyvoice/bin/pip install --no-cache-dir --upgrade pip wheel \
    && /opt/venvs/cosyvoice/bin/pip install --no-cache-dir \
       torch==2.3.1 torchaudio==2.3.1 --index-url https://download.pytorch.org/whl/cu121 \
    && sed -E '/^(--extra-index-url|torch==|torchaudio==|deepspeed==|gradio==|tensorrt-|tensorboard==|fastapi|uvicorn|openai-whisper)/d' \
       /opt/upstreams/CosyVoice/requirements.txt > /tmp/cosyvoice-requirements.txt \
    && /opt/venvs/cosyvoice/bin/pip install --no-cache-dir -r /tmp/cosyvoice-requirements.txt \
    && /opt/venvs/cosyvoice/bin/pip install --no-cache-dir pynini==2.1.5 \
    && /opt/venvs/cosyvoice/bin/pip install --no-cache-dir --no-deps /opt/videoai-src

# MuseTalk 1.5 runtime follows its tested Torch/CUDA combination and omits training/UI-only packages.
RUN python3.10 -m venv /opt/venvs/musetalk \
    && /opt/venvs/musetalk/bin/pip install --no-cache-dir --upgrade pip wheel \
    && /opt/venvs/musetalk/bin/pip install --no-cache-dir \
       torch==2.0.1 torchvision==0.15.2 torchaudio==2.0.2 --index-url https://download.pytorch.org/whl/cu118 \
    && sed -E '/^(tensorflow==|tensorboard==|gradio==)/d' \
       /opt/upstreams/MuseTalk/requirements.txt > /tmp/musetalk-requirements.txt \
    && /opt/venvs/musetalk/bin/pip install --no-cache-dir -r /tmp/musetalk-requirements.txt \
    && /opt/venvs/musetalk/bin/pip install --no-cache-dir openmim \
    && /opt/venvs/musetalk/bin/mim install mmengine==0.10.7 mmcv==2.0.1 mmdet==3.1.0 mmpose==1.1.0 \
    && /opt/venvs/musetalk/bin/pip install --no-cache-dir --no-deps /opt/videoai-src

# Local Qwen translation is optional at invocation time but available in the single image.
RUN python3.10 -m venv /opt/venvs/qwen \
    && /opt/venvs/qwen/bin/pip install --no-cache-dir --upgrade pip wheel \
    && /opt/venvs/qwen/bin/pip install --no-cache-dir \
       torch==2.3.1 --index-url https://download.pytorch.org/whl/cu121 \
    && /opt/venvs/qwen/bin/pip install --no-cache-dir accelerate==1.2.1 transformers==4.53.3 \
    && /opt/venvs/qwen/bin/pip install --no-cache-dir --no-deps /opt/videoai-src

ENV PATH=/opt/venvs/videoai/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    VIDEOAI_UPSTREAM_ROOT=/opt/upstreams \
    VIDEOAI_WHISPER_PYTHON=/opt/venvs/whisper/bin/python \
    VIDEOAI_COSYVOICE_PYTHON=/opt/venvs/cosyvoice/bin/python \
    VIDEOAI_MUSETALK_PYTHON=/opt/venvs/musetalk/bin/python \
    VIDEOAI_QWEN_PYTHON=/opt/venvs/qwen/bin/python \
    PIP_NO_INDEX=1 \
    HF_HUB_OFFLINE=1 \
    HF_DATASETS_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1

WORKDIR /work
ENTRYPOINT ["videoai"]
CMD ["doctor"]
