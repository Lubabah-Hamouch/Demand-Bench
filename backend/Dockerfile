# syntax=docker/dockerfile:1
#
# DemandBench API. The build context is the repository root, because the image needs the
# model bundle in artifacts/lightgbm as well as backend/:
#
#   docker build -f backend/Dockerfile -t demandbench-api .
#
# Listens on $PORT if set (Render sets it), else 8020.

FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.11.7 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /src

# Runtime dependencies only (core + serving extra; no dev tools, Prophet or Kaggle),
# installed before the code so code changes reuse this layer.
COPY backend/pyproject.toml backend/uv.lock backend/.python-version ./
RUN uv sync --frozen --no-dev --extra serving --no-install-project
COPY backend/src ./src
RUN uv sync --frozen --no-dev --extra serving --no-editable


FROM python:3.12-slim
# LightGBM needs the OpenMP runtime.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 app

COPY --from=build /opt/venv /opt/venv
COPY artifacts/lightgbm /app/artifacts/lightgbm

ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    DEMANDBENCH_ARTIFACTS_DIR=/app/artifacts/lightgbm \
    DEMANDBENCH_HOST=0.0.0.0

USER app
WORKDIR /app
EXPOSE 8020
HEALTHCHECK --interval=10s --timeout=5s --start-period=30s --retries=5 \
    CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('PORT', '8020') + '/health', timeout=4)"]
CMD ["python", "-m", "demandbench.serving"]
