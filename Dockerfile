FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --all-extras

COPY alan_t ./alan_t
COPY config ./config
COPY migrations ./migrations
COPY alembic.ini ./
RUN uv sync --frozen --all-extras

ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000
CMD ["uvicorn", "alan_t.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
