FROM ghcr.io/astral-sh/uv:0.12.9 AS uv
FROM python:3.14-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy \
    SEFANG_DATA_ROOT=/data/data \
    SEFANG_STATE_ROOT=/data/state \
    PATH="/app/.venv/bin:$PATH"

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

COPY --from=uv /uv /uvx /bin/

WORKDIR /app
COPY pyproject.toml uv.lock LICENSE NOTICE.md THIRD-PARTY-NOTICES.md README.md ./
COPY licenses ./licenses
COPY vendor ./vendor
COPY src ./src

RUN uv sync --locked --no-dev --no-editable --no-cache

EXPOSE 18943
VOLUME ["/data"]
CMD ["sefang", "serve", "--host", "127.0.0.1", "--port", "18943"]
