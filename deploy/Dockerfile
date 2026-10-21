# syntax=docker/dockerfile:1
# The lipsync-studio connector image: MCP at /mcp behind OAuth, /healthz, behind Caddy.
# Built from the repository root: docker build -f deploy/Dockerfile .
#
# The same base, pinned by tag AND digest, as green-harness's Dockerfile, where the
# digest was proven on 2026-09-25 by
#   curl -sI -H "Authorization: Bearer $TOKEN" \
#     -H "Accept: application/vnd.oci.image.index.v1+json" \
#     https://registry-1.docker.io/v2/library/python/manifests/3.11.16-slim-bookworm
# Python 3.11 is also the lower version this repository's CI runs.

# - stage 1: the dependencies, into a virtualenv -
FROM python:3.11.16-slim-bookworm@sha256:a36c24f9cbdf4fd0f52d67f0823eeac19c2028c637cecc392d97f980d4fec56b AS deps
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /src
COPY requirements-dev.txt ./
# The runtime pins are READ from requirements-dev.txt, not copied into a second list
# (one place for a version). Only what the server imports at run time: the MCP SDK, Starlette, uvicorn,
# and the image/video readers `analyse_creative` uses. The dev tools stay out.
# `extra_ca` is an optional build secret for a TLS-intercepting build proxy, as in the harness.
RUN --mount=type=secret,id=extra_ca \
    if [ -s /run/secrets/extra_ca ]; then export PIP_CERT=/run/secrets/extra_ca; fi \
 && grep -E '^(mcp|starlette|uvicorn|numpy|pillow|imageio-ffmpeg|opencv-python-headless)==' requirements-dev.txt > runtime.txt \
 && test "$(wc -l < runtime.txt)" -eq 7 \
 && python -m venv /opt/venv \
 && /opt/venv/bin/pip install --requirement runtime.txt \
 && /opt/venv/bin/pip freeze > /opt/venv/FROZEN.txt

# - stage 2: the runtime, no build tools, a non-root user -
FROM python:3.11.16-slim-bookworm@sha256:a36c24f9cbdf4fd0f52d67f0823eeac19c2028c637cecc392d97f980d4fec56b
# uid/gid 10002: outside system and login users, and not the harness's 10001, so the two
# services never own each other's files on a shared VPS.
RUN groupadd --system --gid 10002 studio \
 && useradd --system --uid 10002 --gid studio --no-create-home --home-dir /nonexistent \
      --shell /usr/sbin/nologin studio
COPY --from=deps /opt/venv /opt/venv
WORKDIR /app
COPY lipsync/ /app/lipsync/
COPY studio/ /app/studio/
# The knowledge base is written by the server (record_model_fact and friends) and lives
# on a named volume mounted here; docker seeds an EMPTY named volume from this directory
# on first start. /data holds the connector's own SQLite store.
RUN mkdir -p /data && chown -R studio:studio /data /app/studio/knowledge
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONPATH=/app \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    STUDIO_HOST=0.0.0.0 \
    STUDIO_CONNECTOR_DB=/data/connector.sqlite3
USER 10002:10002
EXPOSE 8770
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD ["python", "-c", "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8770/healthz', timeout=4).status == 200 else 1)"]
CMD ["python", "-m", "studio.mcp.http_app", "serve", "--port", "8770"]
