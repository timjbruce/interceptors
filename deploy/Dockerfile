# Shared image for all three first-party services (backend, worker, web).
#
# They are one Python codebase that differs only in the process that launches
# it, so we build a single image and let each Kubernetes Deployment override the
# container command (see deploy/k8s/*.yaml). Build from the repo root:
#
#     docker build -f deploy/Dockerfile -t interceptors:dev .
#
FROM python:3.12-slim

# Predictable, quiet Python in a container.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install dependencies first so this layer caches across code changes.
COPY requirements.txt ./
RUN python -m pip install --upgrade pip && \
    python -m pip install -r requirements.txt

# Application code. All three services live here and share workflows/.
COPY workflows/ ./workflows/
COPY backend/ ./backend/
COPY web/ ./web/

# Some source files ship with restrictive (0600) modes; normalize so the
# unprivileged runtime user can read every module and traverse every dir.
RUN chmod -R a+rX /app

# Run as an unprivileged user.
RUN useradd --create-home --uid 10001 appuser
USER appuser

# Default to the worker; the backend and web Deployments override this.
CMD ["python", "-m", "workflows.worker"]
