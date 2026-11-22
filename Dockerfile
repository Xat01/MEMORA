# MEMORA Dockerfile
# Multi-stage build for minimal, secure runtime image

# ─── Build Stage ───
FROM python:3.12-slim AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies and the memora package to /install
COPY pyproject.toml requirements.txt ./
COPY memora/ ./memora/
RUN pip install --no-cache-dir --prefix=/install \
    -r requirements.txt \
    && pip install --no-cache-dir --prefix=/install uvicorn>=0.30.0 starlette>=0.38.0 \
    && pip install --no-cache-dir --prefix=/install .

# ─── Runtime Stage ───
FROM python:3.12-slim AS runtime

WORKDIR /app

# Install runtime dependencies only
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 1000 memora \
    && useradd --uid 1000 --gid memora --create-home --shell /bin/bash memora

# Copy installed packages from builder (includes memora package with console scripts)
COPY --from=builder /install /usr/local

# Copy entrypoint script
COPY --chown=memora:memora docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Create data directories with correct ownership
RUN mkdir -p /data/chromadb /logs \
    && chown -R memora:memora /data /logs

# Switch to non-root user
USER memora

# Default entrypoint (transport selected by CLI args)
ENTRYPOINT ["docker-entrypoint.sh"]

# Default command: STDIO transport
CMD ["memora-server"]

# Health check command available via: memora doctor --json
# HTTP health endpoints at /health/live, /health/ready, /health/ollama, /health/storage