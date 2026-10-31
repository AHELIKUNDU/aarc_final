"""AARC - AI Analyst and Reasoning Catalyst: FastAPI entry point."""
import json
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from app import models  # noqa: F401  (registers models on Base)
from app.analysis import router as analytics_router
from app.database import Base, engine, get_db
from app.risk import DataValidationError, preview_upload, process_upload

MAX_UPLOAD_MB = 50  # raise this to allow bigger files
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024
PREVIEW_MAX_BYTES = 1024 * 1024  # the preview only needs the start of the file


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create tables on startup if they don't exist
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="AARC API",
    description="AI Analyst and Reasoning Catalyst - data analysis and risk assessment.",
    version="0.4.0",
    lifespan=lifespan,
)

# CORS: allow the React dev servers (Vite = 5173, CRA = 3000)
origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(analytics_router)


@app.get("/", tags=["Health"])
def root():
    return {"app": "AARC", "message": "AARC API is running", "docs": "/docs"}


@app.get("/health", tags=["Health"])
def health():
    return {"status": "ok"}


@app.post("/upload/preview", tags=["Upload"])
def preview_csv(file: UploadFile = File(...)):
    """Look at the start of a CSV: columns, sample rows and the detected column mapping."""
    contents = file.file.read(PREVIEW_MAX_BYTES)
    if not contents:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")
    try:
        return preview_upload(contents)
    except DataValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


# Note: a plain `def` (not `async def`) makes FastAPI run this in a worker thread,
# so a long-running upload does not freeze the rest of the API.
@app.post("/upload", status_code=201, tags=["Upload"])
def upload_csv(
    file: UploadFile = File(...),
    mapping: Optional[str] = Form(None, description='JSON like {"rating": "itemrating", "price": "amount"}'),
    mode: str = Form("auto", description="auto | rules | anomaly"),
    db: Session = Depends(get_db),
):
    """Upload a CSV, clean it, score every row and store the results."""
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only .csv files are supported.")

    mapping_dict = None
    if mapping:
        try:
            mapping_dict = json.loads(mapping)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="'mapping' must be valid JSON.")
        if not isinstance(mapping_dict, dict):
            raise HTTPException(status_code=400, detail="'mapping' must be a JSON object.")

    # Read at most one byte over the limit, so huge files are never fully loaded
    contents = file.file.read(MAX_UPLOAD_BYTES + 1)
    if not contents:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")
    if len(contents) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"File too large (max {MAX_UPLOAD_MB} MB).")

    try:
        return process_upload(db, file.filename, contents, mapping_dict, mode)
    except DataValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
