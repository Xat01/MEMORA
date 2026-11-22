#!/bin/bash
# MEMORA Docker Entrypoint
# Resolves OLLAMA_MODE explicitly (no auto-detection) and delegates to memora-server

set -euo pipefail

# Explicit Ollama mode configuration (no auto-detection)
# Valid values: "host" (default), "container"
OLLAMA_MODE="${OLLAMA_MODE:-host}"

case "${OLLAMA_MODE}" in
    host)
        # Default: host Ollama via Docker Desktop / Linux gateway
        export OLLAMA_HOST="${OLLAMA_HOST:-http://host.docker.internal:11434}"
        # Fallback: container Ollama for cross-validation
        export OLLAMA_HOST_FALLBACK="${OLLAMA_HOST_FALLBACK:-http://ollama:11434}"
        ;;
    container)
        # Containerized Ollama via Compose DNS
        export OLLAMA_HOST="${OLLAMA_HOST:-http://ollama:11434}"
        # Fallback: host Ollama for cross-validation
        export OLLAMA_HOST_FALLBACK="${OLLAMA_HOST_FALLBACK:-http://host.docker.internal:11434}"
        ;;
    *)
        echo "ERROR: Invalid OLLAMA_MODE='${OLLAMA_MODE}'. Use 'host' or 'container'." >&2
        exit 1
        ;;
esac

# Log configuration (without sensitive data)
echo "MEMORA starting with:"
echo "  OLLAMA_MODE=${OLLAMA_MODE}"
echo "  OLLAMA_HOST=${OLLAMA_HOST}"
echo "  OLLAMA_HOST_FALLBACK=${OLLAMA_HOST_FALLBACK}"
echo "  Transport: ${1:-stdio}"

# Delegate to memora-server with all arguments
# Default (no args) = STDIO transport; "http" = HTTP transport
exec memora-server "$@"