"""
FastEmbed Text Embedding Microservice
Production-ready FastAPI service for text embeddings using BAAI/bge-small-en-v1.5.
"""

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Configuration from environment
# ---------------------------------------------------------------------------
EMBED_MODEL_NAME = os.getenv("EMBED_MODEL_NAME", "BAAI/bge-small-en-v1.5")
MAX_BATCH_SIZE = int(os.getenv("MAX_BATCH_SIZE", "128"))
HOST = os.getenv("HOST", "0.0.0.0")  # noqa: S104
PORT = int(os.getenv("PORT", "8003"))
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "*").split(",")

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy model singleton
# ---------------------------------------------------------------------------
_embedder = None


def _load_model(max_retries: int = 5, initial_delay: float = 2.0) -> None:
    global _embedder
    if _embedder is not None:
        return

    import time

    for attempt in range(max_retries):
        try:
            logger.info("Loading embedding model: %s (attempt %d/%d)…", EMBED_MODEL_NAME, attempt + 1, max_retries)
            from fastembed import TextEmbedding

            _embedder = TextEmbedding(model_name=EMBED_MODEL_NAME)
            logger.info("Embedding model loaded successfully.")
            return
        except Exception as e:
            delay = initial_delay * (2**attempt)
            logger.warning(f"Failed to load embedding model (attempt {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                logger.info(f"Retrying in {delay:.1f}s...")
                time.sleep(delay)
            else:
                logger.error("All retry attempts exhausted. Model could not be loaded.")
                raise


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------
class EmbedRequest(BaseModel):
    text: str


class EmbedResponse(BaseModel):
    embedding: list[float]
    dimension: int
    model: str


class BatchEmbedRequest(BaseModel):
    texts: list[str]


class BatchEmbedResponse(BaseModel):
    embeddings: list[list[float]]
    count: int
    dimension: int
    model: str


class ModelInfoResponse(BaseModel):
    model: str
    dimension: int
    max_batch_size: int


class HealthResponse(BaseModel):
    status: str
    model: str


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(_app: FastAPI):
    _load_model()
    yield


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(title="FastEmbed Text Embedding Service", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.get("/health", response_model=HealthResponse)
async def health():
    return HealthResponse(status="ok", model=EMBED_MODEL_NAME)


@app.get("/model_info", response_model=ModelInfoResponse)
async def model_info():
    if _embedder is None:
        raise RuntimeError("Embedding model not loaded")
    dim = next(_embedder.embed(["test"])).shape[0]
    return ModelInfoResponse(model=EMBED_MODEL_NAME, dimension=dim, max_batch_size=MAX_BATCH_SIZE)


@app.post("/embed", response_model=EmbedResponse)
async def embed(req: EmbedRequest):
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="Text must not be empty")

    if _embedder is None:
        raise RuntimeError("Embedding model not loaded")
    embedding = next(_embedder.embed([req.text]))
    return EmbedResponse(
        embedding=embedding.tolist(),
        dimension=len(embedding),
        model=EMBED_MODEL_NAME,
    )


@app.post("/batch_embed", response_model=BatchEmbedResponse)
async def batch_embed(req: BatchEmbedRequest):
    if not req.texts:
        raise HTTPException(status_code=400, detail="Texts list must not be empty")
    if len(req.texts) > MAX_BATCH_SIZE:
        raise HTTPException(status_code=400, detail=f"Batch size {len(req.texts)} exceeds max {MAX_BATCH_SIZE}")

    if _embedder is None:
        raise RuntimeError("Embedding model not loaded")
    embeddings = list(_embedder.embed(req.texts))
    dim = len(embeddings[0]) if embeddings else 0

    return BatchEmbedResponse(
        embeddings=[e.tolist() for e in embeddings],
        count=len(embeddings),
        dimension=dim,
        model=EMBED_MODEL_NAME,
    )


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=HOST, port=PORT)
