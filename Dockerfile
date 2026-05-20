FROM python:3.13-slim

# ripgrep for fs_grep; uv binary copied from the official image for reproducibility
RUN apt-get update \
    && apt-get install -y --no-install-recommends ripgrep \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.10.8 /uv /uvx /usr/local/bin/

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Install dependencies into the cacheable layer (no project source yet)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Install the project itself
COPY src/ ./src/
RUN uv sync --frozen --no-dev

# Non-root runtime user
RUN useradd -r -u 1001 -m -d /home/dewey dewey \
    && chown -R dewey:dewey /app
USER dewey

EXPOSE 8000 8001

CMD ["python", "-m", "dewey.server"]
