# syntax=docker/dockerfile:1.7
#
# Multi-stage Python image for all SibylFi backend services.
# stage 1 (builder): toolchain + libpq-dev + pip wheels into /install
# stage 2 (runtime): slim image with only the runtime libs we link against
#
# Why multi-stage: the final image drops gcc + dev headers (~150MB) and only
# carries libpq5 (runtime). Faster pulls, smaller disk, smaller attack surface.
#
# Cache mounts: --mount=type=cache for /var/cache/apt and /root/.cache/pip
# survive across builds — a requirements.txt bump doesn't re-download from
# PyPI and an apt layer rebuild doesn't re-fetch .deb packages.

# ─── builder ──────────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1
WORKDIR /app

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    rm -f /etc/apt/apt.conf.d/docker-clean \
    && apt-get update \
    && apt-get install -y --no-install-recommends gcc libpq-dev

COPY agents/requirements.txt /app/agents/requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --prefix=/install -r /app/agents/requirements.txt

# ─── runtime ──────────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app

# Only the runtime libpq5 (no gcc, no -dev headers) — matches what psycopg's
# already-built wheel actually links against.
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    rm -f /etc/apt/apt.conf.d/docker-clean \
    && apt-get update \
    && apt-get install -y --no-install-recommends libpq5

COPY --from=builder /install /usr/local

# Application code. Order matters: agents first (most stable), then the more
# frequently-edited modules — keeps each layer's cache hit-rate high.
COPY agents       /app/agents
COPY contracts    /app/contracts
COPY demo         /app/demo
COPY orchestrator /app/orchestrator

# Each compose service overrides CMD with its own uvicorn target.
CMD ["uvicorn", "agents.shared.research_app_factory:build_research_app", "--host", "0.0.0.0", "--port", "7000"]
