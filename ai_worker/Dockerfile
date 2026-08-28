# syntax=docker/dockerfile:1
#
# AI worker image.
#
# CPU-only by default (torch is installed from PyPyTorch's CPU-only index in
# requirements.txt). A café with no GPU should never be forced to pull a
# multi-gigabyte CUDA image just to run the same software on CPU; a GPU
# install overrides the torch install step -- see docs/gpu-setup.md.

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# opencv-python (not headless -- see requirements.txt for why ultralytics
# requires the full build) links against these at import time even though the
# worker never opens a window. Without them `import cv2` fails on this base
# image with "libGL.so.1: cannot open shared object file".
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY ai_worker/requirements.txt /app/requirements.txt
COPY shared/ /app/shared/

RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir -e /app/shared

COPY ai_worker/ /app/

# /app/models is where AI_MODELS_DIR points (docker-compose.ai.yml), backed by
# the ai_models named volume -- created and chowned here, before the volume is
# first attached, so Docker copies this ownership onto the volume and the
# non-root `worker` user below can actually write the downloaded weights into
# it instead of hitting a permission error.
RUN useradd --create-home --uid 10002 worker \
    && mkdir -p /app/models \
    && chown -R worker:worker /app
USER worker

CMD ["python", "-m", "worker"]
