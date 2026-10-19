FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    CONFIG_PATH=/app/config/config.yaml

WORKDIR /app

COPY app/pyproject.toml ./pyproject.toml
COPY app/README.md ./README.md
COPY app/src ./src
COPY app/alembic.ini ./alembic.ini
COPY app/migrations ./migrations
COPY config ./config
# /v1/benchmark serves scripts/bench-results.json, written by scripts/bench.sh.
# Copy the directory (not a wildcard) so the build does not fail when the
# results file has not been generated yet.
COPY scripts ./scripts/

RUN pip install --no-cache-dir .

COPY app/docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh

EXPOSE 8000

CMD ["/app/docker-entrypoint.sh"]
