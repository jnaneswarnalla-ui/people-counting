"""FastAPI backend for the People Counting System.

Run:  uvicorn app:app --host 0.0.0.0 --port 8000
"""
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from threading import Lock

import torch
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.staticfiles import StaticFiles
from ultralytics import YOLO

from counting import process_video

BASE_DIR = Path(__file__).parent
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "outputs"
STATIC_DIR = BASE_DIR / "static"
MODEL_PATH = os.getenv("MODEL_PATH", str(BASE_DIR / "yolov8s.pt"))

MAX_SIZE = 500 * 1024 * 1024
ALLOWED_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv"}
FILE_TTL_SECONDS = 60 * 60          # delete outputs after 1 hour

UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

DEVICE = 0 if torch.cuda.is_available() else "cpu"
state = {"model": None}
jobs = {}
jobs_lock = Lock()
executor = ThreadPoolExecutor(max_workers=1)   # one video at a time


@asynccontextmanager
async def lifespan(app):
    model = YOLO(MODEL_PATH)
    model.to("cuda" if DEVICE == 0 else "cpu")
    state["model"] = model
    print(f"Model loaded on {'GPU' if DEVICE == 0 else 'CPU'}")
    yield


app = FastAPI(title="People Counting System", lifespan=lifespan)


def cleanup_old_files():
    now = time.time()
    for folder in (UPLOAD_DIR, OUTPUT_DIR):
        for f in folder.glob("*"):
            if f.is_file() and now - f.stat().st_mtime > FILE_TTL_SECONDS:
                f.unlink(missing_ok=True)


def update_job(job_id, **fields):
    with jobs_lock:
        jobs[job_id].update(fields)


def run_job(job_id, input_path, output_path, direction, position, invert):
    def on_progress(done, total):
        pct = int(done * 100 / total) if total else 0
        update_job(job_id, progress=min(pct, 99))

    try:
        update_job(job_id, status="processing")
        result = process_video(state["model"], str(input_path), str(output_path),
                               direction=direction, position=position,
                               invert=invert, device=DEVICE,
                               progress_cb=on_progress)
        result["output_url"] = f"/outputs/{output_path.name}"
        update_job(job_id, status="done", progress=100, result=result)
    except Exception as exc:
        update_job(job_id, status="error", error=str(exc))
    finally:
        Path(input_path).unlink(missing_ok=True)


@app.get("/api/health")
def health():
    return {"status": "ok", "model_loaded": state["model"] is not None,
            "device": "gpu" if DEVICE == 0 else "cpu"}


@app.post("/api/process")
async def process(video: UploadFile = File(...),
                  direction: str = Form("horizontal"),
                  position: float = Form(0.5),
                  invert: bool = Form(False)):
    cleanup_old_files()

    ext = Path(video.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, "Please upload an MP4, AVI, MOV or MKV video.")
    if direction not in ("horizontal", "vertical"):
        raise HTTPException(400, "direction must be horizontal or vertical.")
    if not 0.05 <= position <= 0.95:
        raise HTTPException(400, "position must be between 0.05 and 0.95.")

    job_id = uuid.uuid4().hex
    input_path = UPLOAD_DIR / f"{job_id}{ext}"
    output_path = OUTPUT_DIR / f"{job_id}_processed.mp4"

    size = 0
    with open(input_path, "wb") as out:
        while chunk := await video.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_SIZE:
                out.close()
                input_path.unlink(missing_ok=True)
                raise HTTPException(413, "The video must not exceed 500 MB.")
            out.write(chunk)
    if size == 0:
        input_path.unlink(missing_ok=True)
        raise HTTPException(400, "The uploaded video is empty.")

    with jobs_lock:
        jobs[job_id] = {"status": "queued", "progress": 0,
                        "video_name": video.filename}
    executor.submit(run_job, job_id, input_path, output_path,
                    direction, position, invert)
    return {"job_id": job_id}


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str):
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found.")
    return job


app.mount("/outputs", StaticFiles(directory=OUTPUT_DIR), name="outputs")
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="frontend")
