# syntax=docker/dockerfile:1
#
# Backend image: Django + DRF + Channels.
# Deliberately contains no CUDA and no OpenCV — inference lives in the AI worker
# image, which keeps this one small enough to rebuild quickly on a café mini PC.

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# libpq for psycopg, curl for the container healthcheck.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# --------------------------------------------------------------------------- #
# Dependencies — copied before the source so an ordinary code change does not
# reinstall the whole stack.
# --------------------------------------------------------------------------- #
COPY backend/requirements/ /app/requirements/
COPY shared/ /app/shared/

ARG REQUIREMENTS=requirements/prod.txt
RUN pip install --no-cache-dir -r ${REQUIREMENTS} \
    && pip install --no-cache-dir -e /app/shared

# --------------------------------------------------------------------------- #
# Application
# --------------------------------------------------------------------------- #
COPY backend/ /app/

# Run as a non-root user: the container mounts a media volume the café's staff
# can upload logos into, and root-owned files there are a support call.
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/staticfiles /app/mediafiles \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/healthz/ || exit 1

# uvicorn, not gunicorn: the ASGI app serves both HTTP and the WebSocket used by
# the dashboard and the public display.
CMD ["uvicorn", "config.asgi:application", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
