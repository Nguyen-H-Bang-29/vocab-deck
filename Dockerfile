FROM python:3.14-slim

WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Install deps first (cached layer — only rebuilds when lockfile changes)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Copy application code and baked-in enriched vocab data
COPY . .

# Runtime data dir is provided by a mounted volume at container start;
# create the path so state.py's mkdir calls are no-ops on a fresh volume.
RUN mkdir -p /data/runtime/logs

EXPOSE 8080

CMD ["uv", "run", "gunicorn", "app:app", \
     "--bind", "0.0.0.0:8080", \
     "--workers", "1", \
     "--threads", "4", \
     "--timeout", "120"]
