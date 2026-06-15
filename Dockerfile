# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base

# uv for fast, reproducible installs.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install deps first (cached layer), then the project.
COPY pyproject.toml ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-install-project --no-dev || true

COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-dev

EXPOSE 8000

# Factory mode: build_container() wires adapters at startup.
CMD ["uv", "run", "--no-dev", "uvicorn", "alan_t.app.main:create_app", \
     "--factory", "--host", "0.0.0.0", "--port", "8000"]
