# ML Microservices — CLIP Scoring & FastEmbed

Two lightweight FastAPI microservices for image classification and text embeddings, designed for single-VM deployment behind your main application.

| Service | Port | Model | Purpose |
|---------|------|-------|---------|
| **clip** | 8002 | `openai/clip-vit-base-patch32` | Zero-shot image classification |
| **embed** | 8003 | `BAAI/bge-small-en-v1.5` | Text embeddings (384-dim) |

---

## Quick Start (Docker Compose)

```bash
cd microservices
docker compose up --build -d
```

Both services start with health checks and auto-restart. Models are downloaded on first run and cached in the image layer.

## Quick Start (bare metal)

```bash
# CLIP service
cd clip_service
pip install -r requirements.txt
python main.py          # → http://0.0.0.0:8002

# Embed service (separate terminal)
cd embed_service
pip install -r requirements.txt
python main.py          # → http://0.0.0.0:8003
```

## API Reference

### CLIP Service (port 8002)

**Health check**
```
GET /health
```

**Score an image**
```
POST /score
  Form field: image   (file — jpeg/png/webp, max 10 MB)
  Query param: labels  (comma-separated, min 2)

Response:
{
  "scores": {"cat": 0.82, "dog": 0.12, "bird": 0.06},
  "top_label": "cat",
  "top_score": 0.82
}
```

**Batch score**
```
POST /batch_score
  Form field: images  (multiple files)
  Query param: labels

Response:
{
  "results": [
    {"filename": "photo1.jpg", "scores": {...}, "top_label": "cat", ...},
    {"filename": "photo2.png", "scores": {...}, "top_label": "dog", ...}
  ]
}
```

### Embed Service (port 8003)

**Health check**
```
GET /health
```

**Embed a single text**
```
POST /embed
Body: { "text": "Rome is the capital of Italy" }

Response:
{
  "embedding": [0.012, -0.034, ...],
  "dimension": 384,
  "model": "BAAI/bge-small-en-v1.5"
}
```

**Batch embed**
```
POST /batch_embed
Body: { "texts": ["text one", "text two"] }

Response:
{
  "embeddings": [[...], [...]],
  "count": 2,
  "dimension": 384,
  "model": "BAAI/bge-small-en-v1.5"
}
```

**Model info**
```
GET /model_info
```

## Configuration (Environment Variables)

### CLIP Service

| Variable | Default | Description |
|----------|---------|-------------|
| `CLIP_MODEL_NAME` | `openai/clip-vit-base-patch32` | HuggingFace model ID |
| `MAX_FILE_SIZE_MB` | `10` | Max upload size in MB |
| `HOST` | `0.0.0.0` | Bind address |
| `PORT` | `8002` | Listen port |
| `LOG_LEVEL` | `INFO` | Logging level |
| `ALLOWED_ORIGINS` | `*` | CORS origins (comma-separated) |

### Embed Service

| Variable | Default | Description |
|----------|---------|-------------|
| `EMBED_MODEL_NAME` | `BAAI/bge-small-en-v1.5` | HuggingFace model ID |
| `MAX_BATCH_SIZE` | `128` | Max texts per batch request |
| `HOST` | `0.0.0.0` | Bind address |
| `PORT` | `8003` | Listen port |
| `LOG_LEVEL` | `INFO` | Logging level |
| `ALLOWED_ORIGINS` | `*` | CORS origins (comma-separated) |

## Connecting from your main app

```python
import httpx

# Image scoring
resp = httpx.post(
    "http://localhost:8002/score",
    files={"image": open("photo.jpg", "rb")},
    params={"labels": "landmark,museum,restaurant,park"},
)
print(resp.json()["top_label"])

# Text embedding
resp = httpx.post(
    "http://localhost:8003/embed",
    json={"text": "Visit the Colosseum in Rome"},
)
vector = resp.json()["embedding"]
```

## Resource Requirements

| Service | RAM (approx) | Startup Time |
|---------|-------------|--------------|
| CLIP | ~2 GB | ~15 s |
| Embed | ~500 MB | ~5 s |
