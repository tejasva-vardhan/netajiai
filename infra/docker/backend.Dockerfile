# Production-oriented runtime image for the greenfield backend.
# Build from the repository root:
#   docker build -f infra/docker/backend.Dockerfile -t ai-neta-backend:dev .

FROM python:3.13-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN groupadd --system aineta \
    && useradd --system --gid aineta --create-home --home-dir /home/aineta aineta

WORKDIR /app

COPY pyproject.toml requirements.lock ./

RUN python -m pip install --upgrade pip \
    && python -m pip install --require-hashes -r requirements.lock

COPY backend ./backend

RUN python -m pip install --no-deps . \
    && chown -R aineta:aineta /app /home/aineta

USER aineta

EXPOSE 8000

# ECS task definitions should repeat this health check explicitly; ECS does
# not automatically report an image-only Docker health check as task health.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"

# Worker task definitions override this command with one of the installed
# aineta-* entrypoints. No migration or provider call occurs at image build.
CMD ["uvicorn", "backend.app.runtime:app", "--host", "0.0.0.0", "--port", "8000"]
