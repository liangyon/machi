# ── Stage 1: Build ───────────────────────────────────
FROM python:3.11-slim AS builder

# Install uv (fast Python package manager)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy dependency files first (cache layer)
COPY pyproject.toml uv.lock ./

# Install dependencies into a virtual environment
RUN uv sync --frozen --no-dev --no-install-project

# Copy the rest of the application
COPY . .

# Install the project itself
RUN uv sync --frozen --no-dev


# ── Stage 2: Runtime ─────────────────────────────────
FROM python:3.11-slim AS runtime

WORKDIR /app

# Create non-root user for security
RUN groupadd --gid 1000 appuser && \
    useradd --uid 1000 --gid 1000 --create-home appuser

# Copy the virtual environment and app from builder
COPY --from=builder /app /app

# Create data directory for ChromaDB persistence (mount a volume here)
RUN mkdir -p /data/chroma && chown -R appuser:appuser /data

# Switch to non-root user
USER appuser

# Railway injects PORT; default to 8000
ENV PORT=8000
ENV CHROMA_PERSIST_DIR=/data/chroma

EXPOSE ${PORT}

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen(f'http://localhost:{__import__(\"os\").environ.get(\"PORT\", 8000)}/api/health')" || exit 1

# Run with uvicorn — use the venv Python directly (uv not needed at runtime)
CMD /app/.venv/bin/python -m uvicorn app.main:app \
    --host 0.0.0.0 \
    --port ${PORT} \
    --workers 1 \
    --log-level info
