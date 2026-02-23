# Build stage
FROM python:3.13-slim AS builder

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# Install build dependencies
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        libffi-dev \
        libssl-dev \
        libxml2-dev \
        libxslt1-dev \
        libyaml-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Production stage
FROM python:3.13-slim AS runner

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    NTC_TEMPLATES_DIR=/usr/local/lib/python3.13/site-packages/ntc_templates/templates \
    PYTHONPATH=/app

# Install only runtime dependencies and curl for health checks
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
        libxml2 \
        libxslt1.1 \
        libyaml-0-2 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd -r fastapi && useradd -r -g fastapi fastapi

# Copy Python packages from builder
COPY --from=builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Create NTC templates directory
RUN mkdir -p /usr/local/lib/python3.13/site-packages/ntc_templates/templates

# Copy application code
COPY --chown=fastapi:fastapi app ./app
COPY --chown=fastapi:fastapi custom_tasks ./custom_tasks
COPY --chown=fastapi:fastapi main.py ./main.py

# DO NOT copy .env - it's mounted via docker-compose env_file
# The .env file is provided by docker-compose.yml: env_file: "/home/netgrader/netgrader/netgrader-backend-fastapi/.env"

# Switch to non-root user
USER fastapi

EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

# Start FastAPI with uvicorn
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]