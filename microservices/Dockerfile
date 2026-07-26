# ─────────────────────────────────────────────────────────────
# Multi-service Dockerfile — build with --build-arg SERVICE=clip|embed
# ─────────────────────────────────────────────────────────────
FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# System deps for Pillow & torch
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        libgl1 libglib2.0-0 curl && \
    rm -rf /var/lib/apt/lists/*

# ── CLIP service ─────────────────────────────────────────────
FROM base AS clip-deps
COPY clip_service/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download CLIP model during build to avoid runtime latency
RUN python -c "from transformers import CLIPModel, CLIPProcessor; CLIPModel.from_pretrained('openai/clip-vit-base-patch32'); CLIPProcessor.from_pretrained('openai/clip-vit-base-patch32'); print('CLIP model downloaded successfully')"

FROM clip-deps AS clip
COPY clip_service/ ./service/
EXPOSE 8002
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8002/health || exit 1
CMD ["python", "service/main.py"]

# ── Embed service ────────────────────────────────────────────
FROM base AS embed-deps
COPY embed_service/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

FROM embed-deps AS embed
COPY embed_service/ ./service/
EXPOSE 8003
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8003/health || exit 1
CMD ["python", "service/main.py"]
