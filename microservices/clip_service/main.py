"""
CLIP Image Scoring Microservice
Production-ready FastAPI service for image classification using CLIP.
"""

import io
import logging
import os
from contextlib import asynccontextmanager

import torch
from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image
from pydantic import BaseModel
from transformers import CLIPModel, CLIPProcessor

# ---------------------------------------------------------------------------
# Configuration from environment
# ---------------------------------------------------------------------------
CLIP_MODEL_NAME = os.getenv("CLIP_MODEL_NAME", "openai/clip-vit-base-patch32")
MAX_FILE_SIZE_MB = int(os.getenv("MAX_FILE_SIZE_MB", "10"))
HOST = os.getenv("HOST", "0.0.0.0")  # noqa: S104
PORT = int(os.getenv("PORT", "8002"))
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "*").split(",")
ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp", "image/tiff", "image/bmp"}

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy model singletons
# ---------------------------------------------------------------------------
_model: CLIPModel | None = None
_processor: CLIPProcessor | None = None


def _load_model(max_retries: int = 5, initial_delay: float = 2.0) -> None:
    global _model, _processor
    if _model is not None:
        return

    import time

    for attempt in range(max_retries):
        try:
            logger.info("Loading CLIP model: %s (attempt %d/%d)…", CLIP_MODEL_NAME, attempt + 1, max_retries)
            _model = CLIPModel.from_pretrained(CLIP_MODEL_NAME)
            _processor = CLIPProcessor.from_pretrained(CLIP_MODEL_NAME)
            logger.info("CLIP model loaded successfully.")
            return
        except Exception as e:
            delay = initial_delay * (2**attempt)  # Exponential backoff
            logger.warning(f"Failed to load CLIP model (attempt {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                logger.info(f"Retrying in {delay:.1f}s...")
                time.sleep(delay)
            else:
                logger.error("All retry attempts exhausted. Model could not be loaded.")
                raise


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------
class ScoreResponse(BaseModel):
    scores: dict[str, float]
    top_label: str
    top_score: float


class BatchScoreItem(BaseModel):
    filename: str
    scores: dict[str, float]
    top_label: str
    top_score: float


class BatchScoreResponse(BaseModel):
    results: list[BatchScoreItem]


class HealthResponse(BaseModel):
    status: str
    model: str
    device: str


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
app = FastAPI(title="CLIP Image Scoring Service", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _validate_image(file: UploadFile) -> None:
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(status_code=400, detail=f"Unsupported content type: {file.content_type}")


def _score_image(image: Image.Image, labels: list[str]) -> dict[str, float]:
    if _model is None or _processor is None:
        raise RuntimeError("CLIP model not loaded")
    device = "cuda" if torch.cuda.is_available() else "cpu"
    inputs = _processor(text=labels, images=image, return_tensors="pt", padding=True).to(device)
    with torch.no_grad():
        outputs = _model(**inputs)
    logits = outputs.logits_per_image[0].float()
    probs = logits.softmax(dim=-1).cpu().tolist()
    return {label: round(prob, 6) for label, prob in zip(labels, probs, strict=False)}


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.get("/health", response_model=HealthResponse)
async def health():
    device = "cuda" if torch.cuda.is_available() else "cpu"
    return HealthResponse(status="ok", model=CLIP_MODEL_NAME, device=device)


@app.post("/score", response_model=ScoreResponse)
async def score_image(
    image: UploadFile = File(...),
    labels: str = Query(..., description="Comma-separated labels, min 2"),
):
    _validate_image(image)

    label_list = [part.strip() for part in labels.split(",") if part.strip()]
    if len(label_list) < 2:
        raise HTTPException(status_code=400, detail="Provide at least 2 labels")

    contents = await image.read()
    if len(contents) > MAX_FILE_SIZE_MB * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"File exceeds {MAX_FILE_SIZE_MB} MB limit")

    img = Image.open(io.BytesIO(contents)).convert("RGB")
    scores = _score_image(img, label_list)
    top_label = max(scores, key=scores.get)  # type: ignore[arg-type]

    return ScoreResponse(scores=scores, top_label=top_label, top_score=scores[top_label])


@app.post("/batch_score", response_model=BatchScoreResponse)
async def batch_score(
    images: list[UploadFile] = File(...),
    labels: str = Query(..., description="Comma-separated labels, min 2"),
):
    label_list = [part.strip() for part in labels.split(",") if part.strip()]
    if len(label_list) < 2:
        raise HTTPException(status_code=400, detail="Provide at least 2 labels")

    results: list[BatchScoreItem] = []
    for img_file in images:
        _validate_image(img_file)
        file_contents = await img_file.read()
        if len(file_contents) > MAX_FILE_SIZE_MB * 1024 * 1024:
            raise HTTPException(status_code=413, detail=f"{img_file.filename} exceeds {MAX_FILE_SIZE_MB} MB limit")
        img = Image.open(io.BytesIO(file_contents)).convert("RGB")
        scores = _score_image(img, label_list)
        top_label = max(scores, key=scores.get)  # type: ignore[arg-type]
        results.append(
            BatchScoreItem(
                filename=img_file.filename or "unknown", scores=scores, top_label=top_label, top_score=scores[top_label]
            )
        )

    return BatchScoreResponse(results=results)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=HOST, port=PORT)
